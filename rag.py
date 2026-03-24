import json
import os
import requests
import math

DB_FILE = "db.json"

POLZA_API_KEY = os.getenv("POLZA_API_KEY")


# ---------------- EMBEDDINGS ---------------- #

def get_embedding(text):
    try:
        r = requests.post(
            "https://api.polza.ai/v1/embeddings",
            headers={
                "Authorization": f"Bearer {POLZA_API_KEY}"
            },
            json={
                "model": "openai/text-embedding-3-small",
                "input": text[:8000]  # можно больше чем раньше
            },
            timeout=30
        )

        data = r.json()

        if "data" in data:
            return data["data"][0]["embedding"]

        print("Embedding response error:", data)
        return None

    except Exception as e:
        print("Embedding error:", e)
        return None


def cosine_similarity(a, b):
    if not a or not b:
        return 0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0

    return dot / (norm_a * norm_b)


# ---------------- DB ---------------- #

def load_db():
    if not os.path.exists(DB_FILE):
        return []

    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


# ---------------- ADD ---------------- #

def add_papers(papers, user_id):
    db = load_db()
    added = 0

    existing_links = {p["link"] for p in db}

    for p in papers:
        if p["link"] in existing_links:
            continue

        text_for_embedding = f"{p['title']}\n{p['text']}"
        embedding = get_embedding(text_for_embedding)

        if not embedding:
            continue  # пропускаем если embedding не получили

        p["user_id"] = user_id
        p["embedding"] = embedding

        db.append(p)
        added += 1

    save_db(db)
    return added


# ---------------- SEARCH ---------------- #

def search_db(query, user_id, top_k=5):
    db = load_db()

    query_embedding = get_embedding(query)

    if not query_embedding:
        return []

    scored = []

    for p in db:
        if p.get("user_id") != user_id:
            continue

        emb = p.get("embedding")

        if not emb:
            continue

        score = cosine_similarity(query_embedding, emb)
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)

    # фильтр слабых совпадений
    return [p for score, p in scored[:top_k] if score > 0.35]


# ---------------- DELETE ---------------- #

def delete_by_link(user_id, link):
    db = load_db()

    new_db = [
        p for p in db
        if not (p.get("user_id") == user_id and p["link"] == link)
    ]

    if len(new_db) == len(db):
        return False

    save_db(new_db)
    return True


def delete_by_query(user_id, query):
    db = load_db()

    new_db = []
    removed = 0

    for p in db:
        if p.get("user_id") == user_id and query.lower() in p["title"].lower():
            removed += 1
        else:
            new_db.append(p)

    save_db(new_db)
    return removed


# ---------------- STATS ---------------- #

def count_user_articles(user_id):
    db = load_db()
    return len([p for p in db if p.get("user_id") == user_id])


def get_user_papers(user_id):
    db = load_db()
    return [p for p in db if p.get("user_id") == user_id]


# ---------------- CONTEXT ---------------- #

def build_context(docs):
    context = ""

    for p in docs:
        context += f"{p['title']}\n{p['text']}\n\n"

    return context[:4000]