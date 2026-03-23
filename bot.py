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
    load_db,
    build_context
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
POLZA_API_KEY = os.getenv("POLZA_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# кеш переводов (чтобы не платить дважды)
translation_cache = {}


# ---------------- UTILS ---------------- #

def detect_language(text):
    if any("а" <= c.lower() <= "я" for c in text):
        return "ru"
    return "en"


def translate(text, target_lang="Russian"):
    if text in translation_cache:
        return translation_cache[text]

    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "mistralai/mistral-7b-instruct:free",
                "messages": [
                    {"role": "user", "content": f"Translate to {target_lang}: {text}"}
                ],
                "temperature": 0
            },
            timeout=30
        )
        data = r.json()

        if "choices" in data:
            result = data["choices"][0]["message"]["content"]
            translation_cache[text] = result
            return result

    except Exception as e:
        print("TRANSLATE ERROR:", e)

    return text


def llm_answer(context, question):
    prompt = f"""
You are a scientific assistant.

Answer ONLY using the context.
If not enough info, say: Not enough data.

Context:
{context}

Question:
{question}
"""

    free_models = [
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "mistralai/mistral-7b-instruct:free"
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
                    "temperature": 0.3
                },
                timeout=40
            )
            data = r.json()

            if "choices" in data:
                return f"🆓 {model}\n\n" + data["choices"][0]["message"]["content"]

        except Exception as e:
            print("FREE FAIL:", model, e)

    # fallback Polza
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
        return f"❌ LLM error: {e}"


# ---------------- COMMANDS ---------------- #

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("🤖 RAG Scientist ready")


@dp.message(Command("stats"))
async def stats(message: Message):
    db = load_db()
    await message.answer(f"📊 В базе: {len(db)} статей")


@dp.message(Command("search"))
async def search(message: Message):
    query = message.text.replace("/search", "").strip()

    if not query:
        await message.answer("❌ Укажи запрос")
        return

    await message.answer("🔍 Ищу статьи...")

    lang = detect_language(query)
    all_papers = []

    # основной поиск
    all_papers.extend(search_all(query))

    # если русский → добавляем английский
    if lang == "ru":
        translated_query = translate(query, "English")
        all_papers.extend(search_all(translated_query))

    papers = deduplicate(all_papers)
    papers = prepare_papers(papers)

    if not papers:
        await message.answer("❌ Ничего не найдено")
        return

    added = add_papers(papers)

    await message.answer(f"✅ Найдено: {len(papers)}\n💾 Добавлено: {added}")

    # показываем только оригинал + кнопку
    for i, p in enumerate(papers[:3]):
        text = p["text"][:300]

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🌍 Перевести",
                    callback_data=f"translate_{i}"
                )]
            ]
        )

        await message.answer(
            f"📄 {p['title']}\n\n🔗 {p['link']}\n\n📌 {text}...",
            reply_markup=keyboard
        )

    # сохраняем последние статьи (для перевода)
    dp["last_papers"] = papers


# ---------------- CALLBACK ---------------- #

@dp.callback_query(F.data.startswith("translate_"))
async def translate_callback(callback: CallbackQuery):
    index = int(callback.data.split("_")[1])
    papers = dp.get("last_papers", [])

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


# ---------------- ASK ---------------- #

@dp.message(Command("ask"))
async def ask(message: Message):
    query = message.text.replace("/ask", "").strip()

    if not query:
        await message.answer("❌ Укажи вопрос")
        return

    await message.answer("🧠 Думаю...")

    docs = search_db(query)

    if not docs:
        await message.answer("⚠️ Нет данных → ищу...")

        papers = search_all(query)
        papers = deduplicate(papers)
        papers = prepare_papers(papers)

        added = add_papers(papers)

        if not papers:
            await message.answer("❌ Ничего не найдено")
            return

        docs = papers
        await message.answer(f"📚 Добавлено: {added}")

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