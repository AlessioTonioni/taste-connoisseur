import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import llm

app = FastAPI(title="Taste Buddy")

db.init_db()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ── Models ──

class EntryIn(BaseModel):
    title:  str
    type:   str
    review: Optional[str] = None
    date:   Optional[str] = None


class EntryUpdate(BaseModel):
    title:  Optional[str] = None
    type:   Optional[str] = None
    review: Optional[str] = None
    date:   Optional[str] = None


class ProfileSave(BaseModel):
    content: str


# ── Entries ──

@app.get("/entries")
def list_entries(type: Optional[str] = None):
    return db.get_all(type_filter=type)


@app.post("/entries", status_code=201)
def create_entry(entry: EntryIn):
    if entry.type not in db.VALID_TYPES:
        raise HTTPException(400, f"type must be one of {db.VALID_TYPES}")
    return db.create(entry.title, entry.type, entry.review, entry.date)


@app.get("/entries/{entry_id}")
def get_entry(entry_id: int):
    entry = db.get_one(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    return entry


@app.put("/entries/{entry_id}")
def update_entry(entry_id: int, entry: EntryUpdate):
    if not db.get_one(entry_id):
        raise HTTPException(404, "Entry not found")
    if entry.type and entry.type not in db.VALID_TYPES:
        raise HTTPException(400, f"type must be one of {db.VALID_TYPES}")
    return db.update(entry_id, **entry.model_dump())


@app.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int):
    if not db.get_one(entry_id):
        raise HTTPException(404, "Entry not found")
    db.delete(entry_id)


# ── Taste profile ──

@app.get("/profile")
def get_profile():
    return db.get_profile()


@app.put("/profile")
def save_profile(body: ProfileSave):
    return db.save_profile(body.content)


@app.post("/profile/refresh")
def refresh_profile():
    entries = db.get_all_with_reviews()
    if not entries:
        raise HTTPException(400, "No reviewed entries yet — add some first!")

    history = "\n".join(
        f"- [{e['type'].upper()}] ({e['date'] or '?'}) {e['title']}: {e['review']}"
        for e in entries
    )

    prompt = f"""You are analyzing a person's media consumption journal to build their taste profile.
Below is their full log of movies, books, series, and comics with personal reviews.
Reviews are written in Italian, English, or a mix — often informal and humorous. Understand the sentiment regardless of language.

Build a concise taste profile that captures:
- What genres, themes, and styles they gravitate toward
- What they consistently enjoy vs dislike
- Any patterns in tone (e.g. prefer slow burns, hate pretentious art-house, love social commentary)
- Cultural/geographic preferences if visible
- Their critical sensibility (how demanding are they, what impresses them)

Write the profile in second person ("You tend to...", "You appreciate...").
Be specific — reference actual titles or patterns from the log where helpful.
Keep it to ~300 words, structured in short paragraphs. No bullet points.
Respond in English.

Journal:
{history}"""

    content = llm.complete(prompt)
    return db.save_profile(content)


# ── Suggestion helpers ──

def _parse_title_year(suggestion: str) -> tuple[str, Optional[str]]:
    m = re.match(r'\*\*(.+?)\*\*\s*\((\d{4})\)', suggestion.strip())
    if m:
        return m.group(1).strip(), m.group(2)
    m = re.match(r'\*\*(.+?)\*\*', suggestion.strip())
    if m:
        return m.group(1).strip(), None
    return suggestion.split('\n')[0].strip('* '), None


def _wikipedia_thumbnail(title: str) -> Optional[str]:
    try:
        encoded = urllib.parse.quote(title.replace(' ', '_'))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "TasteBuddy/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return data.get("thumbnail", {}).get("source")
    except Exception:
        return None


def _build_links(title: str, media_type: str) -> list[dict]:
    q = urllib.parse.quote_plus(title)
    if media_type in ("movie", "series"):
        return [
            {"label": "IMDb",      "url": f"https://www.imdb.com/find/?q={q}"},
            {"label": "JustWatch", "url": f"https://www.justwatch.com/ch/Suche?q={q}"},
        ]
    else:
        return [
            {"label": "Amazon.it", "url": f"https://www.amazon.it/s?k={q}"},
        ]


# ── Suggestions ──

class SuggestRequest(BaseModel):
    type: str


@app.post("/suggest")
def suggest(body: SuggestRequest):
    if body.type not in db.VALID_TYPES:
        raise HTTPException(400, f"type must be one of {db.VALID_TYPES}")

    # Only send the relevant media type entries to the model
    entries = db.get_all_with_reviews(type_filter=body.type)
    if not entries:
        raise HTTPException(400, f"No reviewed {body.type} entries yet — add some first!")

    from datetime import date
    today = date.today().strftime("%B %Y")

    profile = db.get_profile()
    profile_block = (
        f"\nUser taste profile:\n{profile['content']}\n"
        if profile.get("content") else ""
    )

    history = "\n".join(
        f"- ({e['date'] or '?'}) {e['title']}: {e['review']}"
        for e in entries
    )

    prompt = f"""You are a personal taste advisor. Today is {today}.

Below is a person's {body.type} journal with reviews in Italian, English, or a mix — informal and humorous tone. Understand the sentiment regardless of language.
{profile_block}
Based on the journal and profile, recommend exactly one {body.type} they should watch or read next.

Rules:
- One suggestion only — a single title.
- Write one short paragraph (3-5 sentences max) explaining why it fits their taste.
- Absolutely no spoilers — do not reveal plot twists, endings, or major developments.
- Prefer recent or currently relevant titles where appropriate (today is {today}).
- Do not repeat anything already in their journal.
- Respond in English.

Format your response as:
**Title** (year)
[your paragraph]

{body.type.capitalize()} journal:
{history}"""

    suggestion = llm.complete(prompt)
    title, year = _parse_title_year(suggestion)
    return {
        "suggestion":    suggestion,
        "title":         title,
        "year":          year,
        "image_url":     _wikipedia_thumbnail(title),
        "links":         _build_links(title, body.type),
        "debug_prompt":  prompt,
        "debug_response": suggestion,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
