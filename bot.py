import os
import asyncio
import requests

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

from tools import search_all, deduplicate, prepare_papers
from rag import add_papers, search_db, build_context, db_stats

# --- ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ==============================
# ---------- LLM ---------------
# ==============================

def llm_answer(context, question):
    if not OPENROUTER_API_KEY:
        return "❌ Нет API ключа OPENROUTER"
    
    if not context:
        return "❌ В базе нет информации. Сначала используй /search"

    prompt = f"""
You are a scientific research assistant.

Answer the question strictly based on the provided context.
- Do NOT invent information
- If data is insufficient, say: "Not enough data"
- Be clear and structured

Context:
{context}

Question:
{question}
"""

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen/qwen3-next-80b-a3b-instruct",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3
            },
            timeout=60
        )

        data = response.json()

        if "choices" not in data:
            return f"❌ Ошибка LLM: {data}"

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        return f"❌ Ошибка LLM: {e}"


# ==============================
# ---------- COMMANDS ----------
# ==============================

@dp.message(Command("start"))
async def start(msg: types.Message):
    await msg.answer(
        "🧠 RAG-агент ученого (с LLM)\n\n"
        "Команды:\n"
        "/search тема — найти и сохранить статьи\n"
        "/ask вопрос — задать вопрос\n"
        "/stats — статистика базы\n\n"
        "Пример:\n"
        "/search membrane transport\n"
        "/ask how does ion transport work?"
    )


# ---------- SEARCH ----------
@dp.message(Command("search"))
async def search(msg: types.Message):
    query = msg.text.replace("/search", "").strip()
    
    if not query:
        await msg.answer("❌ Пример:\n/search membrane transport")
        return
    
    await msg.answer("🔍 Ищу статьи...")
    
    papers = search_all(query)
    
    if not papers:
        await msg.answer("❌ Ничего не найдено")
        return
    
    papers = deduplicate(papers)
    papers = prepare_papers(papers)
    
    added_count = add_papers(papers)
    
    await msg.answer(f"✅ Найдено: {len(papers)}\n💾 Добавлено: {added_count}")
    
    for p in papers[:3]:
        text = f"""
📄 {p['title']}

🔗 {p['link']}

📌 {p['text'][:300]}...
"""
        await msg.answer(text)


# ---------- ASK ----------
@dp.message(Command("ask"))
async def ask(msg: types.Message):
    query = msg.text.replace("/ask", "").strip()
    
    if not query:
        await msg.answer("❌ Пример:\n/ask What is ion transport?")
        return
    
    await msg.answer("🧠 Думаю...")
    
    results = search_db(query)
    
    if not results:
        await msg.answer("❌ Нет данных в базе. Сначала /search")
        return
    
    context = build_context(results)
    
    answer = llm_answer(context, query)
    
    # защита от слишком длинных сообщений Telegram
    if len(answer) > 4000:
        answer = answer[:4000] + "\n\n⚠️ Ответ обрезан"
    
    await msg.answer(answer)


# ---------- STATS ----------
@dp.message(Command("stats"))
async def stats(msg: types.Message):
    stats = db_stats()
    
    await msg.answer(
        f"📊 В базе статей: {stats['total_papers']}"
    )


# ---------- RUN ----------

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())