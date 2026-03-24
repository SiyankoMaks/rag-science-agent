import requests
import feedparser
import re
from urllib.parse import quote


# ---------- Очистка HTML ----------
def clean_html(text):
    if not text:
        return ""
    return re.sub('<.*?>', '', text)


# ---------- arXiv ----------
def search_arxiv(query, max_results=5):
    try:
        encoded_query = quote(query)
        url = f"http://export.arxiv.org/api/query?search_query=all:{encoded_query}&max_results={max_results}"
        
        feed = feedparser.parse(url)
        
        papers = []
        
        for entry in feed.entries:
            papers.append({
                "title": entry.title,
                "text": entry.summary,
                "link": entry.link,
                "source": "arxiv"
            })
        
        return papers
    
    except Exception as e:
        print("arXiv error:", e)
        return []


# ---------- CrossRef ----------
def search_crossref(query, max_results=5):
    try:
        url = "https://api.crossref.org/works"
        
        params = {
            "query": query,
            "rows": max_results
        }
        
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        papers = []
        
        for item in data.get("message", {}).get("items", []):
            title = item.get("title", [""])
            doi = item.get("DOI")
            abstract = clean_html(item.get("abstract", ""))
            
            papers.append({
                "title": title[0] if title else "No title",
                "text": abstract,
                "link": f"https://doi.org/{doi}" if doi else "",
                "source": "crossref"
            })
        
        return papers
    
    except Exception as e:
        print("CrossRef error:", e)
        return []


# ---------- Общий поиск ----------
def search_all(query, max_results=5):
    results = []
    
    arxiv_results = search_arxiv(query, max_results)
    crossref_results = search_crossref(query, max_results)
    
    results.extend(arxiv_results)
    results.extend(crossref_results)
    
    return results


# ---------- Удаление дубликатов ----------
def deduplicate(papers):
    seen = set()
    unique = []
    
    for p in papers:
        key = (p["title"], p["link"])
        
        if key not in seen:
            seen.add(key)
            unique.append(p)
    
    return unique


# ---------- Ограничение длины текста ----------
def truncate_text(text, max_len=1000):
    if not text:
        return ""
    
    text = text.replace("\n", " ").strip()
    
    if len(text) > max_len:
        return text[:max_len] + "..."
    
    return text


# ---------- Подготовка результатов ----------

def is_relevant(text, query):
    query_words = query.lower().split()
    text = text.lower()

    return any(w in text for w in query_words)

def prepare_papers(papers, query=None):
    prepared = []

    for p in papers:
        text = p.get("text", "")

        if query and not is_relevant(text, query):
            continue

        prepared.append({
            "title": p.get("title", ""),
            "text": truncate_text(text),
            "link": p.get("link", ""),
            "source": p.get("source", "")
        })

    return prepared