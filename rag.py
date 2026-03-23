import json
import os

DB_FILE = "database.json"

STOPWORDS = {
    "what", "is", "how", "does", "the", "in", "on", "at",
    "with", "a", "an", "of", "to", "and", "explain", "detail"
}


# ---------- Загрузка базы ----------
def load_db():
    if not os.path.exists(DB_FILE):
        return []
    
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


# ---------- Сохранение базы ----------
def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------- Добавление статей ----------
def add_papers(papers):
    db = load_db()
    
    existing_links = set(p.get("link") for p in db)
    
    new_items = []
    
    for p in papers:
        if p.get("link") not in existing_links:
            new_items.append(p)
    
    db.extend(new_items)
    save_db(db)
    
    return len(new_items)


# ---------- Поиск ----------
def search_db(query, top_k=5):
    db = load_db()
    
    results = []
    
    query_words = [
        w for w in query.lower().split()
        if len(w) > 3 and w not in STOPWORDS
    ]
    
    for p in db:
        text = (p.get("title", "") + " " + p.get("text", "")).lower()
        
        score = sum(1 for word in query_words if word in text)
        
        if score > 0:
            results.append((score, p))
    
    results.sort(key=lambda x: x[0], reverse=True)
    
    # fallback
    if not results:
        return db[:top_k]
    
    return [p for _, p in results[:top_k]]


# ---------- Контекст ----------
def build_context(papers, max_chars=3000):
    context = ""
    
    for p in papers:
        chunk = f"""
TITLE: {p.get("title", "")}
TEXT: {p.get("text", "")}
SOURCE: {p.get("link", "")}
-----------------------
"""
        if len(context) + len(chunk) > max_chars:
            break
        
        context += chunk
    
    return context.strip()


# ---------- Статистика ----------
def db_stats():
    db = load_db()
    
    return {
        "total_papers": len(db)
    }