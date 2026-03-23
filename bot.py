import os
import asyncio
import requests

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command

from rag import (
    search_articles,
    add_articles_to_db,
    get_all_articles,
    build_context
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
POLZA_API_KEY = os.getenv("POLZA_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------------- LLM ---------------- #

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
        "mistralai/mistral-7b-instruct:free",
        "openchat/openchat-7b:free"
    ]

    # --- FREE ---
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

    # --- POLZA ---
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

        return f"❌ Polza error: {data}"

    except Exception as e:
        return f"❌ LLM error: {e}"


# ---------------- COMMANDS ---------------- #

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("🤖 RAG Scientist ready\n\n/search <query>\n/ask <question>\n/stats")


@dp.message(Command("stats"))
async def stats(message: Message):
    articles = get_all_articles()
    await message.answer(f"📊 В базе: {len(articles)} статей")


@dp.message(Command("search"))
async def search(message: Message):
    query = message.text.replace("/search", "").strip()

    if not query:
        await message.answer("❌ Укажи запрос: /search <query>")
        return

    await message.answer("🔍 Ищу статьи...")

    articles = search_articles(query)

    if not articles:
        await message.answer("❌ Ничего не найдено")
        return

    added = add_articles_to_db(articles)

    await message.answer(f"✅ Найдено: {len(articles)}\n💾 Добавлено: {added}")

    for art in articles[:3]:
        await message.answer(
            f"📄 {art['title']}\n\n🔗 {art['link']}\n\n📌 {art['summary'][:300]}..."
        )


@dp.message(Command("ask"))
async def ask(message: Message):
    query = message.text.replace("/ask", "").strip()

    if not query:
        await message.answer("❌ Укажи вопрос: /ask <question>")
        return

    await message.answer("🧠 Думаю...")

    # --- 1. поиск в БД ---
    docs = search_articles(query)
    print("Docs found:", len(docs))

    # --- 2. авто-поиск ---
    if not docs:
        await message.answer("⚠️ Нет данных → ищу...")

        new_articles = search_articles(query)
        added = add_articles_to_db(new_articles)

        if not new_articles:
            await message.answer("❌ Ничего не найдено")
            return

        docs = new_articles
        await message.answer(f"📚 Добавлено: {added}")

    # --- 3. контекст ---
    context = build_context(docs)

    if len(context) < 200:
        await message.answer("❌ Недостаточно данных")
        return

    # --- 4. LLM ---
    answer = llm_answer(context, query)

    await message.answer(answer)


# ---------------- RUN ---------------- #

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())