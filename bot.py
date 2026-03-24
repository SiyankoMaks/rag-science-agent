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
    delete_by_link,
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
Answer the question using the context if relevant.

- If context is useful → use it
- If context is weak → answer generally
- Keep answer short and clear

Context:
{context}

Question:
{question}
"""

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
        en_query = translate(query, "English")
        all_papers += search_all(en_query)

    all_papers = deduplicate(all_papers)

    papers = prepare_papers(deduplicate(all_papers), query)
    papers = [p for p in papers if len(p["text"]) > 300]

    if not papers:
        await message.answer("❌ Ничего не найдено")
        return

    added = add_papers(papers, message.from_user.id)
    last_search_cache[message.from_user.id] = papers

    titles = "\n".join(f"• {p['title'][:80]}" for p in papers[:5])

    await message.answer(
        f"✅ Найдено: {len(papers)}\n"
        f"💾 Добавлено: {added}\n\n"
        f"📚 Примеры:\n{titles}"
    )

    for i, p in enumerate(papers[:3]):
        buttons = []

        if detect_language(p["title"]) == "en":
            buttons.append(
                InlineKeyboardButton(text="🌍 Перевести", callback_data=f"translate_{i}")
            )

        buttons.append(
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"delete_{p['link']}"
            )
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


def build_list_page(papers, page, per_page=5):
    total_pages = max(1, (len(papers) + per_page - 1) // per_page)

    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    end = start + per_page

    items = papers[start:end]

    text = f"📚 Твои статьи (стр. {page+1}/{total_pages}):\n\n"

    for i, p in enumerate(items, start=start + 1):
        text += f"{i}. {p['title'][:80]}\n"

    # кнопки
    buttons = []

    if page > 0:
        buttons.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"list_{page-1}")
        )

    if page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton(text="➡️", callback_data=f"list_{page+1}")
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons] if buttons else [])

    return text, keyboard


@dp.message(Command("list"))
async def list_cmd(message: Message):
    papers = get_user_papers(message.from_user.id)

    if not papers:
        await message.answer("📭 У тебя нет статей")
        return

    text, keyboard = build_list_page(papers, page=0)

    await message.answer(text, reply_markup=keyboard)


# ---------------- VIEW ---------------- #

@dp.message(Command("view"))
async def view_cmd(message: Message):
    try:
        idx = int(message.text.split()[1]) - 1
    except:
        await message.answer("❌ Укажи ID")
        return

    papers = get_user_papers(message.from_user.id)

    if idx < 0 or idx >= len(papers):
        await message.answer("❌ Нет статьи")
        return

    p = papers[idx]

    buttons = []

    if detect_language(p["title"]) == "en":
        buttons.append(
            InlineKeyboardButton(
                text="🌍 Перевести",
                callback_data=f"translate_view_{idx}"
            )
        )

    buttons.append(
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"delete_{p['link']}"
        )
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

    await message.answer(
        f"📄 {p['title']}\n\n{p['text']}\n\n🔗 {p['link']}",
        reply_markup=keyboard
    )


# ---------------- ASK ---------------- #

def is_relevant(query, paper):
    q = set(query.lower().split())
    text = (paper.get("title", "") + paper.get("text", "")).lower()
    return sum(1 for w in q if w in text) >= 2


def simple_rerank(query, papers):
    query_words = set(query.lower().split())
    scored = []

    for p in papers:
        text = (p.get("title", "") + " " + p.get("text", "")).lower()
        score = sum(1 for w in query_words if w in text)
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for score, p in scored if score > 0]


@dp.message(Command("ask"))
async def ask(message: Message):
    query = message.text.replace("/ask", "").strip()

    if not query:
        await message.answer("❌ Укажи вопрос")
        return

    await message.answer("🧠 Думаю...")

    lang = detect_language(query)

    search_query = query
    if lang == "ru":
        search_query = translate(query, "English")

    print("QUERY:", search_query)

    docs = search_db(search_query, message.from_user.id)

    print("DOCS FOUND:", len(docs))

    # ---------------- ЕСЛИ НЕТ В БД ---------------- #
    if not docs:
        await message.answer("⚠️ Нет данных\n🔍 Ищу статьи...")

        papers = search_all(search_query)

        papers = prepare_papers(deduplicate(papers), search_query)

        papers = simple_rerank(search_query, papers)

        papers = [p for p in papers if is_relevant(search_query, p)]

        papers = [
            p for p in papers
            if len(p.get("text", "")) > 150
        ]

        if not papers:
            answer = llm_answer("", search_query)

            if lang == "ru":
                answer = translate(answer, "Russian")

            answer = "⚠️ Ответ без источников\n\n" + answer

            await message.answer(answer)
            return

        add_papers(papers[:10], message.from_user.id)

        docs = papers[:5]

        titles = "\n".join(
            f"{i+1}. {p['title'][:80]}"
            for i, p in enumerate(papers)
        )

        await message.answer(
            f"📚 Найдено и добавлено: {len(papers)}\n\n"
            f"📄 Все статьи:\n{titles}"
        )

    # ---------------- ГЕНЕРАЦИЯ ОТВЕТА ---------------- #

    if docs:
        context = build_context(docs)
        answer = llm_answer(context, search_query)
    else:
        answer = llm_answer("", search_query)
        answer = "⚠️ Ответ без источников\n\n" + answer

    if lang == "ru":
        answer = translate(answer, "Russian")

    await message.answer(answer)


# ---------------- CALLBACKS ---------------- #

@dp.callback_query(F.data.regexp(r"^translate_\d+$"))
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


@dp.callback_query(F.data.startswith("translate_view_"))
async def translate_view_callback(callback: CallbackQuery):
    try:
        idx = int(callback.data.split("_")[2])
    except:
        await callback.answer("Ошибка")
        return

    papers = get_user_papers(callback.from_user.id)

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
    link = callback.data.replace("delete_", "", 1)

    success = delete_by_link(callback.from_user.id, link)

    if success:
        await callback.message.answer("🗑 Удалено")
    else:
        await callback.message.answer("❌ Ошибка")

    await callback.answer()


@dp.callback_query(F.data.startswith("list_"))
async def list_pagination(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])

    papers = get_user_papers(callback.from_user.id)

    text, keyboard = build_list_page(papers, page)

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


# ---------------- RUN ---------------- #

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())