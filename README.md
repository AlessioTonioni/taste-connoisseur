# Taste Connoisseur

A personal media journal and AI-powered recommendation app. Log movies, books, series, and comics with free-text reviews, and get tailored suggestions based on your taste history.

> **Personal project disclaimer:** This is a personal side project built in my own time. It is not affiliated with, endorsed by, or connected to my employer (Google) in any way.

---

## What it does

- **Log** media you've watched or read, with free-text reviews in any language
- **Build** a taste profile that captures your preferences over time
- **Get suggestions** from an AI assistant that knows your history and taste

## Stack

- **Backend:** FastAPI + SQLite — simple, no external database needed
- **Frontend:** Plain HTML/JS — no framework, no build step
- **AI:** Anthropic Claude or Google Gemini (configurable), with web search enabled for up-to-date recommendations

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Run with Anthropic (Claude)

```bash
ANTHROPIC_API_KEY=sk-... .venv/bin/python main.py
```

### Run with Gemini

```bash
GEMINI_API_KEY=... .venv/bin/python main.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## Configuration

Model names can be changed in `config.json` without touching any code:

```json
{
  "anthropic_model": "claude-opus-4-6",
  "gemini_model": "gemini-3-flash-preview"
}
```

Changes take effect immediately without restarting the server.

## Data

All data is stored locally in a single SQLite file (`taste_buddy.db`). Nothing is sent anywhere except the AI API calls (your review history is included in the prompt to generate suggestions).
