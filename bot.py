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
    count_user_articles,
    get_user_papers
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
POLZA_API_KEY = os.getenv("POLZA_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

translation_cache = {}
user_papers_cache = {}
last_search_cache = {}

PAGE_SIZE = 5


# ---------------- UTILS ---------------- #

def detect_language(text):
    if any("а" <= c.lower() <= "я" for c in text):
        return "ru"
    return "en"


def translate(text, target_lang="Russian"):
    key = f"{text}_{target_lang}"

    if key in translation_cache:
        return translation_cache[key]

    prompt = f"Translate to {target_lang}. Only translation:\n{text}"

    # FREE
    for model in [
        "mistralai/mistral-7b-instruct:free",
        "qwen/qwen3-next-80b-a3b-instruct:free"
    ]:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0
                },
                timeout=30
            )
            data = r.json()

            if "choices" in data:
                res = data["choices"][0]["message"]["content"].strip()
                if res.lower() != text.lower():
                    translation_cache[key] = res
                    return res
        except:
            pass

    # POLZA
    try:
        r = requests.post(
            "https://api.polza.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {POLZA_API_KEY}"},
            json={
                "model": "qwen/qwen3-next-80b-a3b-instruct",
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=60
        )
        data = r.json()

        if "choices" in data:
            res = data["choices"][0]["message"]["content"]
            translation_cache[key] = res
            return res

    except:
        pass

    return text


def llm_answer(context, question):
    prompt = f"""
Answer using ONLY the context.
If not enough data say: Not enough data.

Context:
{context}

Question:
{question}
"""

    # FREE
    for model in ["qwen/qwen3-next-80b-a3b-instruct:free"]:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = r.json()

            if "choices" in data:
                return data["choices"][0]["message"]["content"]

        except:
            pass

    # POLZA
    try:
        r = requests.post(
            "https://api.polza.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {POLZA_API_KEY}"},
            json={
                "model": "qwen/qwen3-next-80b-a3b-instruct",
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        return r.json()["choices"][0]["message"]["content"]

    except:
        return "❌ Ошибка"


# ---------------- COMMANDS ---------------- #

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("🤖 RAG Scientist ready\nНапиши /help")


@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer("""
📚 Команды:

/search <запрос> — найти статьи  
/ask <вопрос> — задать вопрос  
/list — список статей  
/view <id> — открыть статью  
/delete <текст> — удалить  
/stats — статистика  
""")


@dp.message(Command("stats"))
async def stats(message: Message):
    count = count_user_articles(message.from_user.id)
    await message.answer(f"📊 Твоих статей: {count}")


# ---------------- SEARCH ---------------- #

@dp.message(Command("search"))
async def search(message: Message):
    query = message.text.replace("/search", "").strip()

    if not query:
        await message.answer("❌ Укажи запрос")
        return

    await message.answer("🔍 Ищу статьи...")

    all_papers = search_all(query)

    if detect_language(query) == "ru":
        all_papers += search_all(translate(query, "English"))

    papers = prepare_papers(deduplicate(all_papers))

    if not papers:
        await message.answer("❌ Ничего не найдено")
        return

    added = add_papers(papers, message.from_user.id)
    last_search_cache[message.from_user.id] = papers

    await message.answer(f"✅ Найдено: {len(papers)}\n💾 Добавлено: {added}")

    for i, p in enumerate(papers[:3]):
        buttons = []

        if detect_language(p["title"]) == "en":
            buttons.append(
                InlineKeyboardButton(text="🌍 Перевести", callback_data=f"translate_{i}")
            )

        buttons.append(
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{i}")
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

        await message.answer(
            f"📄 {p['title']}\n\n🔗 {p['link']}\n\n📌 {p['text'][:300]}...",
            reply_markup=keyboard
        )


# ---------------- DELETE ---------------- #

@dp.message(Command("delete"))
async def delete(message: Message):
    query = message.text.replace("/delete", "").strip()

    if not query:
        await message.answer("❌ Укажи текст")
        return

    removed = delete_by_query(message.from_user.id, query)
    await message.answer(f"🗑 Удалено: {removed}")


# ---------------- LIST ---------------- #

def build_keyboard(page, total):
    buttons = []

    if page > 0:
        buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"page_{page-1}"))

    if (page + 1) * PAGE_SIZE < total:
        buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"page_{page+1}"))

    return InlineKeyboardMarkup(inline_keyboard=[buttons])


@dp.message(Command("list"))
async def list_cmd(message: Message):
    papers = get_user_papers(message.from_user.id)

    if not papers:
        await message.answer("📭 Нет статей")
        return

    user_papers_cache[message.from_user.id] = papers
    await send_page(message, papers, 0)


async def send_page(message, papers, page):
    start = page * PAGE_SIZE
    chunk = papers[start:start + PAGE_SIZE]

    text = "\n\n".join(
        f"{i+start}. {p['title'][:80]}"
        for i, p in enumerate(chunk)
    )

    await message.answer(
        f"📚 Статьи:\n\n{text}",
        reply_markup=build_keyboard(page, len(papers))
    )


@dp.callback_query(F.data.startswith("page_"))
async def page_callback(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    papers = user_papers_cache.get(callback.from_user.id, [])

    await send_page(callback.message, papers, page)
    await callback.answer()


# ---------------- VIEW ---------------- #

@dp.message(Command("view"))
async def view_cmd(message: Message):
    try:
        idx = int(message.text.split()[1])
    except:
        await message.answer("❌ Укажи ID")
        return

    papers = get_user_papers(message.from_user.id)

    if idx >= len(papers):
        await message.answer("❌ Нет статьи")
        return

    p = papers[idx]

    await message.answer(
        f"📄 {p['title']}\n\n{p['text']}\n\n🔗 {p['link']}"
    )


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


# ---------------- CALLBACKS ---------------- #

@dp.callback_query(F.data.startswith("translate_"))
async def translate_callback(callback: CallbackQuery):
    idx = int(callback.data.split("_")[1])
    papers = last_search_cache.get(callback.from_user.id, [])

    if idx >= len(papers):
        await callback.answer("Ошибка")
        return

    p = papers[idx]

    await callback.message.answer(
        f"🌍 ПЕРЕВОД:\n\n{translate(p['title'])}\n\n{translate(p['text'][:500])}"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_"))
async def delete_callback(callback: CallbackQuery):
    idx = int(callback.data.split("_")[1])

    success = delete_paper_by_index(callback.from_user.id, idx)

    if success:
        await callback.message.answer("🗑 Удалено")
    else:
        await callback.message.answer("❌ Ошибка")

    await callback.answer()


# ---------------- RUN ---------------- #

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())