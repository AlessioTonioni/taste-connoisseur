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


# ── Streaming config ──

_CONFIG_PATH = Path(__file__).parent / "config.json"


def _read_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except Exception:
        return {}


def _write_config(updates: dict) -> dict:
    cfg = _read_config()
    cfg.update(updates)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return cfg


class StreamingConfig(BaseModel):
    streaming_country:  str
    streaming_services: list[str]


@app.get("/config/streaming")
def get_streaming_config():
    cfg = _read_config()
    return {
        "streaming_country":  cfg.get("streaming_country", "Switzerland"),
        "streaming_services": cfg.get("streaming_services", []),
    }


@app.put("/config/streaming")
def save_streaming_config(body: StreamingConfig):
    cfg = _write_config({
        "streaming_country":  body.streaming_country,
        "streaming_services": body.streaming_services,
    })
    return {
        "streaming_country":  cfg["streaming_country"],
        "streaming_services": cfg["streaming_services"],
    }


# ── Suggestions ──

class SuggestRequest(BaseModel):
    type:           str
    streaming_bias: bool = False
    comfort_level:  int = 3


@app.post("/suggest")
def suggest(body: SuggestRequest):
    if body.type not in db.VALID_TYPES:
        raise HTTPException(400, f"type must be one of {db.VALID_TYPES}")

    # Only send the relevant media type entries to the model (last 5)
    entries = db.get_all_with_reviews(type_filter=body.type)[:5]
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

    streaming_block = ""
    if body.streaming_bias and body.type in ("movie", "series"):
        cfg = _read_config()
        services = cfg.get("streaming_services", [])
        country  = cfg.get("streaming_country", "Switzerland")
        if services:
            svc_list = ", ".join(services)
            streaming_block = (
                f"- Strongly prefer titles currently available to stream in {country} "
                f"on one of these services: {svc_list}. "
                f"Use web search to verify availability if needed. "
                f"If no great match is streamable there, you may suggest it anyway but note that.\n"
            )

    comfort_map = {
        1: "Strictly within their comfort zone. Suggest something that perfectly matches their established tastes and patterns. A very safe bet.",
        2: "Mostly within their comfort zone. Suggest something that matches their taste well but might have one or two fresh elements.",
        3: "A balanced recommendation. Suggest something that aligns with their profile but introduces some new themes or styles.",
        4: "Experimental. Lean outside their usual preferences. Suggest something that might be a bit of a stretch but has a clear hook based on their interests.",
        5: "Completely outside their comfort zone. Be bold and suggest something drastically different from their usual log, but that you think they will appreciate for a specific reason you must explain.",
    }
    comfort_instruction = comfort_map.get(body.comfort_level, comfort_map[3])

    prompt = f"""You are a personal taste advisor. Today is {today}.

Below is a person's taste profile and the last 5 entries from their {body.type} journal.
Reviews are in Italian, English, or a mix — informal and humorous tone. Understand the sentiment regardless of language.
{profile_block}
Context for the recommendation:
{comfort_instruction}

Based on the journal and profile, recommend exactly one {body.type} they should watch or read next.

Rules:
- One suggestion only — a single title.
- Write one short paragraph (3-5 sentences max) explaining why it fits their taste (or why they should try it if it's out of their comfort zone).
- In the rationale, explicitly touch upon why this matches the requested 'comfort zone' level (e.g. why it's a safe bet or why it's an interesting risk).
- Absolutely no spoilers — do not reveal plot twists, endings, or major developments.
- Prefer recent or currently relevant titles where appropriate (today is {today}).
- Do not repeat anything already in their journal.
{streaming_block}- Respond in English.

Format your response as:
**Title** (year)
[your paragraph]

Last 5 {body.type} journal entries:
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
