import os
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

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
dp = Dispatcher(bot)

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

@dp.message_handler(commands=['start'])
async def start(msg: types.Message):
    await msg.reply("🤖 RAG Scientist ready\n\n/search <query>\n/ask <question>\n/stats")


@dp.message_handler(commands=['stats'])
async def stats(msg: types.Message):
    articles = get_all_articles()
    await msg.reply(f"📊 В базе: {len(articles)} статей")


@dp.message_handler(commands=['search'])
async def search(msg: types.Message):
    query = msg.get_args()

    if not query:
        await msg.reply("❌ Укажи запрос: /search <query>")
        return

    await msg.reply("🔍 Ищу статьи...")

    articles = search_articles(query)

    if not articles:
        await msg.reply("❌ Ничего не найдено")
        return

    added = add_articles_to_db(articles)

    await msg.reply(f"✅ Найдено: {len(articles)}\n💾 Добавлено: {added}")

    for art in articles[:3]:
        await msg.reply(f"📄 {art['title']}\n\n🔗 {art['link']}\n\n📌 {art['summary'][:300]}...")


@dp.message_handler(commands=['ask'])
async def ask(msg: types.Message):
    query = msg.get_args()

    if not query:
        await msg.reply("❌ Укажи вопрос: /ask <question>")
        return

    await msg.reply("🧠 Думаю...")

    # --- 1. Ищем в БД ---
    docs = search_articles(query)
    print("Docs found:", len(docs))

    # --- 2. Если нет → авто-поиск ---
    if not docs:
        await msg.reply("⚠️ Нет данных → пробую найти...")

        new_articles = search_articles(query)
        added = add_articles_to_db(new_articles)

        if not new_articles:
            await msg.reply("❌ Ничего не найдено даже после поиска")
            return

        docs = new_articles
        await msg.reply(f"📚 Найдено и добавлено: {added}")

    # --- 3. Строим контекст ---
    context = build_context(docs)

    if len(context) < 200:
        await msg.reply("❌ Недостаточно данных в статьях")
        return

    # --- 4. LLM ---
    answer = llm_answer(context, query)

    await msg.reply(answer)


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)