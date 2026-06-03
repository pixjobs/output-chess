# ♞ OUTPUT//CHESS

A retro-styled chess arena where engines battle each other — or you can jump in and take them on yourself.

Built as a gift for a chess-loving 8-year-old champion. Slick enough for grown-ups, fun enough for future grandmasters.

---

## Features

| Mode | What happens |
|------|-------------|
| ⚔ **Bot vs Bot** | Two engines play at configurable strength. Watch and learn. |
| ♟ **Play vs Bot** | Face the machine. Pick your colour and your opponent's strength. |

**Three engines out of the box:**

| Engine | Strength | Notes |
|--------|----------|-------|
| ♞ Stockfish | ~400–3200 ELO | World's strongest open-source engine. Skill Level 0–20. |
| ⚡ Stockfish Blitz | ~300–900 ELO | Same brain, 20 ms time cap. Plays fast and fallibly. |
| 🎲 RandomBot | ~100–300 ELO | Pure chaos. Picks any legal move. Great for beginners. |

Adding more engines is a one-line change — see [Adding Engines](#adding-engines).

---

## Quick Start

```bash
git clone https://github.com/pixjobs/output-chess
cd output-chess

# 1. Download Stockfish for your platform → https://stockfishchess.org/download
#    Place the binary at ./stockfish (or set STOCKFISH_PATH env var)

# 2. Install Python dependencies
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Run
python3 server.py
# → http://localhost:5500
```

The repo ships with a pre-built frontend in `frontend/dist`. To rebuild it after editing:

```bash
cd frontend && npm install && npm run build
```

---

## Deploy to GCP Cloud Run

One command — Cloud Run detects the Dockerfile, installs Stockfish via apt, builds the frontend, and deploys:

```bash
gcloud run deploy outputchess \
  --source . \
  --region us-central1 \
  --allow-unauthenticated
```

No binary to bundle. The ARM binary on your dev machine stays local; the container gets the correct x86-64 build automatically.

---

## Project Structure

```
output-chess/
├── server.py            # Flask API + engine orchestration
├── requirements.txt     # Python deps (flask, python-chess, gunicorn, flask-cors)
├── Dockerfile           # Multi-stage: node build → python runtime → gunicorn
├── vercel.json          # Frontend-only config for Vercel (needs separate backend)
├── play_game.py         # CLI: watch two engines play in the terminal
└── frontend/
    ├── src/
    │   ├── App.tsx      # React app — all game logic and UI
    │   └── index.css    # Spaceship dark theme with retro accents
    ├── dist/            # Pre-built, served by Flask
    └── package.json
```

---

## Adding Engines

Add one entry to `ENGINE_REGISTRY` in `server.py` and restart. No frontend changes needed — the engine appears in both dropdowns automatically.

```python
ENGINE_REGISTRY["maia_1500"] = {
    "name": "Maia 1500",
    "path": "/usr/local/bin/lc0",       # any UCI-compatible engine
    "skill_range": (0, 0),
    "min_elo": 1450,
    "max_elo": 1550,
}
```

Optional fields:

| Field | Default | Effect |
|-------|---------|--------|
| `time_limit` | `0.5` | Max seconds per move (lower = weaker) |
| `random_bot` | `False` | Skip UCI, play a random legal move |

---

## Tech Stack

- **Backend** — Python 3.12 · Flask · python-chess · Gunicorn
- **Engine** — [Stockfish](https://stockfishchess.org) (GPL-3.0) via UCI protocol
- **Frontend** — React 19 · TypeScript · [react-chessboard](https://github.com/Clariity/react-chessboard) v5 · Vite
- **Font** — [Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P) (retro pixel logo)
- **Deploy** — Docker / GCP Cloud Run

---

## License

MIT — use it, fork it, teach a kid chess with it. ♟

Built with ♟ by [pixjobs](https://github.com/pixjobs).
