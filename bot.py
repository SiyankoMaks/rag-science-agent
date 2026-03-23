import os
import asyncio

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

from tools import search_all, deduplicate, prepare_papers
from rag import add_papers, search_db, build_context, db_stats

# --- ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ---------- Простое LLM (пока без API) ----------
def llm_answer(context, question):
    if not context:
        return "❌ В базе нет информации. Сначала используй /search"
    
    return f"""
🧠 Ответ на основе найденных статей:

Вопрос: {question}

--- Контекст ---
{context[:1500]}

(⚠️ Это базовый режим без LLM. Позже подключим GPT)
"""


# ==============================
# ---------- COMMANDS ----------
# ==============================

@dp.message(Command("start"))
async def start(msg: types.Message):
    await msg.answer(
        "🧠 RAG-агент ученого запущен\n\n"
        "Команды:\n"
        "/search тема — найти и сохранить статьи\n"
        "/ask вопрос — задать вопрос по базе\n"
        "/stats — статистика базы\n\n"
        "Пример:\n"
        "/search membrane transport\n"
        "/ask How does ion transport work?"
    )


# ---------- ПОИСК И СОХРАНЕНИЕ ----------
@dp.message(Command("search"))
async def search(msg: types.Message):
    query = msg.text.replace("/search", "").strip()
    
    if not query:
        await msg.answer("❌ Пример:\n/search membrane transport")
        return
    
    await msg.answer("🔍 Ищу статьи...")
    
    # поиск
    papers = search_all(query)
    
    if not papers:
        await msg.answer("❌ Ничего не найдено")
        return
    
    # очистка
    papers = deduplicate(papers)
    papers = prepare_papers(papers)
    
    # сохранить в базу
    added_count = add_papers(papers)
    
    await msg.answer(f"✅ Найдено: {len(papers)}\n💾 Добавлено в базу: {added_count}")
    
    # показать немного
    for p in papers[:3]:
        text = f"""
📄 {p['title']}

🔗 {p['link']}

📌 {p['text'][:300]}...
"""
        await msg.answer(text)


# ---------- ВОПРОС К БАЗЕ ----------
@dp.message(Command("ask"))
async def ask(msg: types.Message):
    query = msg.text.replace("/ask", "").strip()
    
    if not query:
        await msg.answer("❌ Пример:\n/ask What is ion transport?")
        return
    
    await msg.answer("🧠 Думаю...")
    
    # поиск по базе
    results = search_db(query)
    
    if not results:
        await msg.answer("❌ Ничего не найдено в базе. Сначала сделай /search")
        return
    
    # собираем контекст
    context = build_context(results)
    
    # ответ (пока без GPT)
    answer = llm_answer(context, query)
    
    await msg.answer(answer)


# ---------- СТАТИСТИКА ----------
@dp.message(Command("stats"))
async def stats(msg: types.Message):
    stats = db_stats()
    
    await msg.answer(
        f"📊 В базе статей: {stats['total_papers']}"
    )


# ---------- запуск ----------

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())