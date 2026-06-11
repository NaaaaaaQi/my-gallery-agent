# My Gallery Agent

**[🌐 Live Gallery Database →](https://naaaaaaqi.github.io/my-gallery-agent/)**

A personal AI agent deployed via [OpenClaw](https://github.com/openclaw/openclaw), connected to Telegram and powered by Claude (Anthropic). The agent specializes in the Bay Area art scene — tracking galleries, open calls, and upcoming events across San Francisco, the East Bay, Peninsula, and South Bay.

---

## What This Does

- **Telegram interface** — chat with your agent directly from your phone; no app to install
- **Persistent knowledge base** — a curated database of 60+ Bay Area galleries with open call status, artist-friendliness ratings, addresses, and upcoming events
- **Web search** — DuckDuckGo plugin for real-time lookups when the knowledge base needs supplementing
- **Session memory** — remembers context across conversations
- **Claude Sonnet 4.6** — Anthropic's latest model for fast, accurate responses
- **Self-hosted** — runs on your own machine via Docker; your data stays with you

---

## Architecture

```
Telegram ──► OpenClaw Gateway (Docker)
                    │
                    ├── Claude API (Anthropic)
                    ├── DuckDuckGo web search
                    ├── Session memory (SQLite)
                    ├── SOUL.md (persona + knowledge base pointer)
                    └── GALLERY_DATABASE.md (60+ galleries, curated)
```

The gateway runs as a persistent Docker container. The workspace volume (`openclaw-workspace`) holds all state — persona, gallery data, and conversation history — separately from the container so it survives restarts and image updates.

---

## Gallery Knowledge Base

`GALLERY_DATABASE.md` is a structured database covering:

| Region | Coverage |
|--------|----------|
| San Francisco | 25+ galleries — SoMa, Mission, Dogpatch, Castro, Potrero Hill |
| East Bay | 15+ galleries — Oakland Uptown, Jingletown, Berkeley |
| Peninsula / South Bay | 10+ galleries — Palo Alto, Los Altos, Los Gatos, San Jose SoFA |
| Santa Cruz / North Bay | Felix Kulpa, Gallery Route One, and more |
| Blue-chip / Academic | Berggruen, Jessica Silverman, Pace Palo Alto, CCA Wattis (for reference) |

Each entry includes:
- Open call status (🟢 active / 🔴 monitor)
- Emerging-artist friendliness rating (⭐–⭐⭐⭐)
- Website, address, submission contact
- Newsletter subscription status
- Upcoming event dates

The knowledge base is a plain Markdown file — update it anytime and the agent picks up changes on the next conversation.

---

## Stack

| Component | Technology |
|-----------|-----------|
| Agent runtime | [OpenClaw](https://github.com/openclaw/openclaw) |
| AI model | Claude Sonnet 4.6 (`anthropic/claude-sonnet-4-6`) |
| Messaging channel | Telegram Bot API |
| Web search | DuckDuckGo plugin |
| Infrastructure | Docker Compose |
| Persistence | Docker named volume |

---

## Setup

### Prerequisites
- Docker Desktop
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- Telegram bot token ([@BotFather](https://t.me/BotFather) → `/newbot`)

### Deploy

```bash
git clone https://github.com/NaaaaaaQi/my-gallery-agent
cd my-gallery-agent

# Fix volume ownership
docker run --rm --user root -v openclaw-workspace:/workspace \
  ghcr.io/openclaw/openclaw:latest chown -R 1000:1000 /workspace

# Onboard (replace with your keys)
docker compose run --rm openclaw openclaw onboard \
  --non-interactive --accept-risk --flow quickstart \
  --auth-choice apiKey \
  --anthropic-api-key 'sk-ant-...' \
  --workspace /workspace \
  --skip-channels --skip-search --skip-skills --skip-hooks \
  --no-install-daemon --skip-health

# Add Telegram
docker compose run --rm openclaw openclaw channels add \
  --channel telegram --token '<BOT_TOKEN>' --name 'My Gallery Agent'

# Set model
docker compose run --rm openclaw openclaw models set anthropic/claude-sonnet-4-6

# Enable plugins
docker compose run --rm openclaw openclaw plugins enable duckduckgo
docker compose run --rm openclaw openclaw hooks enable session-memory

# Start
docker compose up -d openclaw-gateway
```

### Pair with Telegram
1. Message your bot `/start` in Telegram
2. Copy the pairing code it returns
3. Run: `docker exec openclaw-gateway openclaw pairing approve telegram <CODE>`

### Load the knowledge base
```bash
docker cp GALLERY_DATABASE.md openclaw-gateway:/workspace/GALLERY_DATABASE.md
docker cp SOUL.md openclaw-gateway:/workspace/SOUL.md
docker compose restart openclaw-gateway
```

### Access the dashboard
```bash
# Get your login token
docker exec openclaw-gateway sh -c \
  'node -e "console.log(require(process.env.OPENCLAW_STATE_DIR+\"/openclaw.json\").gateway.auth.token)"'
```
Open: `http://127.0.0.1:18789/#token=<TOKEN>`

---

## Automated Status Updates

`scripts/update_gallery_status.py` scrapes every gallery's website and uses Claude Haiku to detect active open calls, submission deadlines, and upcoming events — then rewrites `GALLERY_DATABASE.md` and syncs it into the running container automatically.

```bash
# Install dependencies (one-time)
pip3 install httpx beautifulsoup4 anthropic

# Run a full update
ANTHROPIC_API_KEY=sk-ant-... python3 scripts/update_gallery_status.py

# Preview changes without writing files
ANTHROPIC_API_KEY=sk-ant-... python3 scripts/update_gallery_status.py --dry-run

# Check a single gallery
ANTHROPIC_API_KEY=sk-ant-... python3 scripts/update_gallery_status.py --gallery "Mercury 20"
```

Sample output:
```
Checking 45 galleries...
  [1/45] Mercury 20 Gallery (mercurytwenty.com) ✓
  [2/45] ARC Gallery (arc-sf.com) ✓
  ...

────────────────────────────────────────────────────
  Gallery Status Update — 2026-06-10
────────────────────────────────────────────────────

🟢  OPEN CALL DETECTED (3)
    • Mercury 20 Gallery
        → Artist Reception and Talk — Saturday, May 16, 3–5pm
        ℹ Actively seeking new artist members for their collective

    • Gray Loft Gallery
        → Call for Entry open — annual color-theme juried show
        ℹ Deadline June 30; submit via callforentry.org

🔴  NO ACTIVE CALL (38)
    • Berggruen Gallery — invitation only, no submission info
    ...

    Total checked: 45  |  Updated: 41  |  Errors: 4
────────────────────────────────────────────────────
```

The script skips blue-chip / invitation-only galleries automatically. Run it weekly to keep the database current.

---

## Customization

**Update the gallery database** — edit `GALLERY_DATABASE.md` locally, then:
```bash
docker cp GALLERY_DATABASE.md openclaw-gateway:/workspace/GALLERY_DATABASE.md
```
No restart needed.

**Change the persona** — edit `SOUL.md`, then:
```bash
docker cp SOUL.md openclaw-gateway:/workspace/SOUL.md
docker compose restart openclaw-gateway
```

**Switch models** — any model in the OpenClaw catalog:
```bash
docker compose run --rm openclaw openclaw models list
docker compose run --rm openclaw openclaw models set anthropic/claude-opus-4-8
```

---

## License

MIT
