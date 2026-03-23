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


# ---------- Нормализация ----------
def normalize_query(q: str):
    return q.lower().strip()


# ==============================
# ---------- LLM ---------------
# ==============================

def llm_answer(context, question):
    if not context:
        return "❌ В базе нет информации. Сначала используй /search"

    prompt = f"""
You are a scientific assistant.

Answer the question ONLY using the provided context.
If the answer is not in the context, say: "Not enough data".

Context:
{context}

Question:
{question}
"""

    # ---------- FREE MODELS ----------
    free_models = [
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "mistralai/mistral-7b-instruct:free",
        "openchat/openchat-7b:free"
    ]

    # ---------- 1. Пытаемся free ----------
    for model in free_models:
        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
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

            data = response.json()

            if "choices" in data:
                return f"🆓 {model}\n\n" + data["choices"][0]["message"]["content"]

        except Exception as e:
            print("Free model failed:", model, e)

    # ---------- 2. FALLBACK → POLZA ----------
    try:
        response = requests.post(
            url="https://api.polza.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('POLZA_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen/qwen3-next-80b-a3b-instruct",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            },
            timeout=60
        )

        data = response.json()

        if "choices" in data:
            return "💰 Polza (paid)\n\n" + data["choices"][0]["message"]["content"]

        return f"❌ Polza error: {data}"

    except Exception as e:
        return f"❌ Все модели недоступны: {e}"


# ==============================
# ---------- COMMANDS ----------
# ==============================

@dp.message(Command("start"))
async def start(msg: types.Message):
    await msg.answer(
        "🧠 RAG-агент ученого (LLM)\n\n"
        "/search тема\n"
        "/ask вопрос\n"
        "/stats"
    )


# ---------- SEARCH ----------
@dp.message(Command("search"))
async def search(msg: types.Message):
    query = normalize_query(msg.text.replace("/search", ""))
    
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
        await msg.answer(
            f"📄 {p['title']}\n\n🔗 {p['link']}\n\n📌 {p['text'][:300]}..."
        )


# ---------- ASK ----------
@dp.message(Command("ask"))
async def ask(msg: types.Message):
    query = normalize_query(msg.text.replace("/ask", ""))
    
    if not query:
        await msg.answer("❌ Пример:\n/ask What is ion transport?")
        return
    
    await msg.answer("🧠 Думаю...")
    
    results = search_db(query)
    
    if not results:
        await msg.answer("❌ Нет данных в базе")
        return
    
    context = build_context(results)
    
    answer = llm_answer(context, query)
    
    if len(answer) > 4000:
        answer = answer[:4000] + "\n\n⚠️ Ответ обрезан"
    
    await msg.answer(answer)


# ---------- STATS ----------
@dp.message(Command("stats"))
async def stats(msg: types.Message):
    stats = db_stats()
    await msg.answer(f"📊 В базе: {stats['total_papers']} статей")


# ---------- RUN ----------
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())