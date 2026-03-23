import json
import os

DB_FILE = "db.json"


def load_db():
    if not os.path.exists(DB_FILE):
        return []

    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def add_papers(papers, user_id):
    db = load_db()
    added = 0

    existing_links = {p["link"] for p in db}

    for p in papers:
        if p["link"] in existing_links:
            continue

        p["user_id"] = user_id
        db.append(p)
        added += 1

    save_db(db)
    return added


# 🔥 УЛУЧШЕННЫЙ ПОИСК
def search_db(query, user_id):
    db = load_db()
    results = []

    query = query.lower()
    words = query.split()

    for p in db:
        if p.get("user_id") != user_id:
            continue

        text = (p["title"] + " " + p["text"]).lower()

        score = sum(1 for w in words if w in text)

        if score > 0:
            results.append((score, p))

    results.sort(key=lambda x: x[0], reverse=True)

    return [p for _, p in results[:5]]


def delete_paper_by_index(user_id, index):
    db = load_db()

    user_papers = [p for p in db if p.get("user_id") == user_id]

    if index >= len(user_papers):
        return False

    paper = user_papers[index]

    new_db = [
        p for p in db
        if not (p["link"] == paper["link"] and p.get("user_id") == user_id)
    ]

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


def count_user_articles(user_id):
    db = load_db()
    return len([p for p in db if p.get("user_id") == user_id])


def get_user_papers(user_id):
    db = load_db()
    return [p for p in db if p.get("user_id") == user_id]


def build_context(docs):
    context = ""

    for p in docs:
        context += f"{p['title']}\n{p['text']}\n\n"

    return context[:4000]