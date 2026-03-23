import os
import asyncio
import requests

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command

from tools import search_all, prepare_papers, deduplicate
from rag import (
    search_db,
    add_papers,
    build_context,
    delete_paper_by_index,
    delete_by_query,
    count_user_articles
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
POLZA_API_KEY = os.getenv("POLZA_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

translation_cache = {}
user_papers = {}


# ---------------- UTILS ---------------- #

def detect_language(text):
    if any("а" <= c.lower() <= "я" for c in text):
        return "ru"
    return "en"


def translate(text, target_lang="Russian"):
    cache_key = f"{text}_{target_lang}"

    if cache_key in translation_cache:
        return translation_cache[cache_key]

    prompt = f"""
Translate the following text to {target_lang}.

IMPORTANT:
- Return ONLY translated text
- Do NOT repeat original

TEXT:
{text}
"""

    # -------- FREE -------- #
    free_models = [
        "mistralai/mistral-7b-instruct:free",
        "qwen/qwen3-next-80b-a3b-instruct:free"
    ]

    for model in free_models:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0
                },
                timeout=30
            )

            data = r.json()

            if "choices" in data:
                result = data["choices"][0]["message"]["content"].strip()

                # защита от "не перевёл"
                if result.lower() != text.lower():
                    translation_cache[cache_key] = result
                    return result

        except Exception as e:
            print("FREE TRANSLATE FAIL:", model, e)

    # -------- POLZA -------- #
    try:
        r = requests.post(
            "https://api.polza.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {POLZA_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen/qwen3-next-80b-a3b-instruct",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0
            },
            timeout=60
        )

        data = r.json()

        if "choices" in data:
            result = data["choices"][0]["message"]["content"].strip()

            translation_cache[cache_key] = result
            return result

    except Exception as e:
        print("POLZA TRANSLATE FAIL:", e)

    return text


def llm_answer(context, question):
    prompt = f"""
You are a scientific assistant.

Answer ONLY using the context.
If not enough info, say: Not enough data.

Answer in the same language as the question.

Context:
{context}

Question:
{question}
"""

    free_models = [
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "mistralai/mistral-7b-instruct:free"
    ]

    # -------- FREE -------- #
    for model in free_models:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                },
                timeout=40
            )

            data = r.json()

            if "choices" in data:
                return f"🆓 {model}\n\n" + data["choices"][0]["message"]["content"]

        except Exception as e:
            print("FREE LLM FAIL:", model, e)

    # -------- POLZA -------- #
    try:
        r = requests.post(
            "https://api.polza.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {POLZA_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen/qwen3-next-80b-a3b-instruct",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            },
            timeout=60
        )

        data = r.json()

        if "choices" in data:
            return "💰 Polza\n\n" + data["choices"][0]["message"]["content"]

    except Exception as e:
        print("POLZA LLM FAIL:", e)

    return "❌ Ошибка LLM"


# ---------------- COMMANDS ---------------- #

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("🤖 RAG Scientist ready")


@dp.message(Command("stats"))
async def stats(message: Message):
    count = count_user_articles(message.from_user.id)
    await message.answer(f"📊 Твоих статей: {count}")


@dp.message(Command("search"))
async def search(message: Message):
    query = message.text.replace("/search", "").strip()

    if not query:
        await message.answer("❌ Укажи запрос")
        return

    await message.answer("🔍 Ищу статьи...")

    lang = detect_language(query)
    all_papers = []

    all_papers.extend(search_all(query))

    if lang == "ru":
        translated = translate(query, "English")
        all_papers.extend(search_all(translated))

    papers = prepare_papers(deduplicate(all_papers))

    if not papers:
        await message.answer("❌ Ничего не найдено")
        return

    added = add_papers(papers, message.from_user.id)

    await message.answer(f"✅ Найдено: {len(papers)}\n💾 Добавлено: {added}")

    user_papers[message.from_user.id] = papers

    for i, p in enumerate(papers[:3]):
        buttons = []

        if detect_language(p["title"]) == "en":
            buttons.append(
                InlineKeyboardButton(
                    text="🌍 Перевести",
                    callback_data=f"translate_{i}"
                )
            )

        buttons.append(
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"delete_{i}"
            )
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

        await message.answer(
            f"📄 {p['title']}\n\n🔗 {p['link']}\n\n📌 {p['text'][:300]}...",
            reply_markup=keyboard
        )


@dp.message(Command("delete"))
async def delete(message: Message):
    query = message.text.replace("/delete", "").strip()

    if not query:
        await message.answer("❌ Укажи часть названия")
        return

    removed = delete_by_query(message.from_user.id, query)

    await message.answer(f"🗑 Удалено: {removed}")


# ---------------- CALLBACK ---------------- #

@dp.callback_query(F.data.startswith("translate_"))
async def translate_callback(callback: CallbackQuery):
    index = int(callback.data.split("_")[1])
    papers = user_papers.get(callback.from_user.id, [])

    if index >= len(papers):
        await callback.answer("Ошибка")
        return

    p = papers[index]

    title_ru = translate(p["title"], "Russian")
    text_ru = translate(p["text"][:500], "Russian")

    await callback.message.answer(
        f"🌍 ПЕРЕВОД:\n\n{title_ru}\n\n{text_ru}"
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("delete_"))
async def delete_callback(callback: CallbackQuery):
    index = int(callback.data.split("_")[1])

    success = delete_paper_by_index(callback.from_user.id, index)

    if success:
        await callback.message.answer("🗑 Статья удалена")
    else:
        await callback.message.answer("❌ Ошибка удаления")

    await callback.answer()


# ---------------- ASK ---------------- #

@dp.message(Command("ask"))
async def ask(message: Message):
    query = message.text.replace("/ask", "").strip()

    if not query:
        await message.answer("❌ Укажи вопрос")
        return

    await message.answer("🧠 Думаю...")

    docs = search_db(query, message.from_user.id)

    if not docs:
        await message.answer("⚠️ Нет данных\n🔍 Ищу статьи...")

        papers = search_all(query)

        if detect_language(query) == "ru":
            papers += search_all(translate(query, "English"))

        papers = prepare_papers(deduplicate(papers))

        if not papers:
            await message.answer("❌ Ничего не найдено")
            return

        add_papers(papers, message.from_user.id)
        docs = papers

        await message.answer(f"📚 Найдено и добавлено: {len(papers)}")

    context = build_context(docs)

    if len(context) < 200:
        await message.answer("❌ Недостаточно данных")
        return

    answer = llm_answer(context, query)

    await message.answer(answer)


# ---------------- RUN ---------------- #

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())