#!/usr/bin/env python3
"""
Converts GALLERY_DATABASE.md into a filterable HTML page.
Output goes to docs/index.html (GitHub Pages compatible).

Usage:
    python3 scripts/generate_html.py
"""

import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

DB_PATH = os.path.expanduser("~/projects/openclaw/GALLERY_DATABASE.md")
OUT_DIR  = os.path.expanduser("~/projects/openclaw/docs")
OUT_PATH = os.path.join(OUT_DIR, "index.html")

TODAY = date.today().isoformat()

# ── Parser ────────────────────────────────────────────────────────────────────

@dataclass
class Gallery:
    name: str
    region: str
    url: str = ""
    address: str = ""
    description: str = ""
    friendliness: int = 0          # 0–3 stars
    open_call: str = "unknown"     # "open" | "closed" | "unknown"
    bluechip: bool = False
    newsletter: bool = False
    open_call_note: str = ""
    events: str = ""
    notes: str = ""
    excluded: bool = False
    tags: List[str] = field(default_factory=list)


def count_stars(text: str) -> int:
    return min(text.count("⭐"), 3)


def parse_db(md_text: str) -> tuple:
    lines = md_text.splitlines()
    galleries: List[Gallery] = []
    events_section: List[str] = []
    resources_section: List[str] = []
    actions_section: List[str] = []
    current_region = "其他"
    in_excluded = False
    in_events = False
    in_resources = False
    in_actions = False
    i = 0

    while i < len(lines):
        line = lines[i]

        # top-level section headers
        if line.startswith("## "):
            heading = line[3:].strip()
            in_excluded = "排除" in heading
            in_events = "近期活动" in heading or "Open Call 截止" in heading
            in_resources = "订阅资源" in heading
            in_actions = "快速行动" in heading
            if not in_excluded and not in_events and not in_resources and not in_actions:
                current_region = heading
            i += 1
            continue

        if in_events and line.strip().startswith("|") and "画廊" not in line and "---" not in line:
            events_section.append(line)
            i += 1
            continue

        if in_resources and line.strip().startswith("|") and "平台" not in line and "---" not in line:
            resources_section.append(line)
            i += 1
            continue

        if in_actions and line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.")):
            actions_section.append(line.strip())
            i += 1
            continue

        # gallery header
        if line.startswith("### "):
            name_raw = line[4:].strip()
            is_bluechip = "🔵" in name_raw
            is_excluded = in_excluded
            stars = count_stars(name_raw)
            name_clean = re.sub(r"[⭐🔵🔴🟢⚠️✅❌📧]+", "", name_raw).strip()

            g = Gallery(
                name=name_clean,
                region=current_region,
                friendliness=stars,
                bluechip=is_bluechip,
                excluded=is_excluded,
            )

            # scan the block lines
            j = i + 1
            while j < len(lines):
                bl = lines[j]
                if bl.startswith("### ") or bl.startswith("## ") or bl.startswith("---"):
                    break

                # table row or list item
                content = bl
                for cell in re.split(r"\|", content):
                    cell = cell.strip()
                    if not cell or cell == "项目" or cell == "内容" or set(cell) == {"-"}:
                        continue
                    cell_low = cell.lower()

                    if "Website:" in bl or "网址" in bl:
                        m = re.search(r"https?://([^\s\)]+)", bl)
                        if not m:
                            m = re.search(r"([a-z0-9.\-]+\.[a-z]{2,})", bl, re.I)
                        if m:
                            g.url = m.group(1).rstrip("/").lower()

                    elif ("Address:" in bl or "地址" in bl) and not g.address:
                        addr = re.sub(r"\[.*?\]\(.*?\)", "", bl)
                        addr = re.sub(r"^-\s*(Address:|地址:?)\s*", "", addr).strip()
                        g.address = addr[:80]

                    elif ("About:" in bl or "定位" in bl) and not g.description:
                        desc = re.sub(r"^-\s*(About:|定位:?)\s*", "", bl).strip()
                        g.description = re.sub(r"[*_]", "", desc)[:100]

                    elif "newsletter" in cell_low or "newsletter" in bl.lower():
                        g.newsletter = "📧" in bl

                    elif "open call" in bl.lower():
                        if "🟢" in bl:
                            g.open_call = "open"
                        elif "🔴" in bl:
                            g.open_call = "closed"
                        note = re.sub(r"^-\s*Open Call:?\s*", "", bl, flags=re.I).strip()
                        note = re.sub(r"[🟢🔴]", "", note).strip()
                        note = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", note)
                        g.open_call_note = note[:120]

                    elif "Events:" in bl or "近期活动" in bl:
                        evt = re.sub(r"^-\s*(Events:|近期活动:?)\s*", "", bl).strip()
                        evt = re.sub(r"\*\*([^\*]+)\*\*", r"\1", evt)
                        g.events = evt[:150]

                    elif ("Notes:" in bl or "备注" in bl) and not g.notes:
                        note = re.sub(r"^-\s*(Notes:|备注:?)\s*", "", bl).strip()
                        g.notes = re.sub(r"\*\*([^\*]+)\*\*", r"\1", note)[:150]

                j += 1

            if g.name and g.name not in ("项目",):
                galleries.append(g)
            i = j
            continue

        i += 1

    return galleries, events_section, resources_section, actions_section


# ── HTML template ─────────────────────────────────────────────────────────────

def gallery_card(g: Gallery) -> str:
    if g.excluded:
        return ""

    stars_html = "⭐" * g.friendliness if g.friendliness else ""
    bluechip_badge = '<span class="badge badge-blue">Blue-chip</span>' if g.bluechip else ""

    if g.open_call == "open":
        status_badge = '<span class="badge badge-green">🟢 Open Call</span>'
    elif g.open_call == "closed":
        status_badge = '<span class="badge badge-red">🔴 Monitor</span>'
    else:
        status_badge = '<span class="badge badge-gray">Unknown</span>'

    url_html = f'<a href="https://{g.url}" target="_blank" class="gallery-url">{g.url} ↗</a>' if g.url else ""
    addr_html = f'<div class="gallery-addr">📍 {g.address}</div>' if g.address else ""
    desc_html = f'<div class="gallery-desc">{g.description}</div>' if g.description else ""
    note_html = f'<div class="gallery-note">📋 {g.open_call_note}</div>' if g.open_call_note else ""
    events_html = f'<div class="gallery-event">🗓 {g.events}</div>' if g.events else ""

    tags_data = f'data-region="{g.region}" data-open="{g.open_call}" data-stars="{g.friendliness}" data-blue="{str(g.bluechip).lower()}"'

    import urllib.parse
    gallery_slug = urllib.parse.quote(g.name)
    apply_url = f"https://naaaaaaqi.github.io/human-artark/apply/?gallery={gallery_slug}"
    apply_btn = f'<a href="{apply_url}" class="apply-btn" target="_blank">Apply →</a>'

    return f"""
<div class="card" {tags_data}>
  <div class="card-header">
    <div class="card-title-row">
      <h3 class="card-name">{g.name}</h3>
      <div class="card-badges">{stars_html} {bluechip_badge} {status_badge}</div>
    </div>
    {url_html}
  </div>
  <div class="card-body">
    {addr_html}
    {desc_html}
    {note_html}
    {events_html}
  </div>
  <div class="card-footer">
    {apply_btn}
  </div>
</div>"""


def events_table(rows: List[str]) -> str:
    if not rows:
        return ""
    cells = []
    for row in rows:
        parts = [p.strip() for p in row.split("|") if p.strip()]
        if len(parts) >= 2:
            name = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", parts[0])
            activity = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", parts[1])
            date_str = parts[2] if len(parts) > 2 else ""
            date_str = re.sub(r"\*\*([^\*]+)\*\*", r"\1", date_str)
            cells.append(f"<tr><td>{name}</td><td>{activity}</td><td>{date_str}</td></tr>")
    if not cells:
        return ""
    return f"""
<div class="events-section">
  <h2>📅 Upcoming Events & Deadlines</h2>
  <table class="events-table">
    <thead><tr><th>Gallery / Organization</th><th>Event / Exhibition</th><th>Date</th></tr></thead>
    <tbody>{"".join(cells)}</tbody>
  </table>
</div>"""


def actions_list(rows: List[str]) -> str:
    if not rows:
        return ""
    strip_num = lambda r: re.sub(r'^\d+\.\s*', '', r)
    items = "".join(f"<li>{strip_num(r)}</li>" for r in rows)
    return f"""
<div class="actions-section">
  <h2>💡 Quick Action Checklist</h2>
  <ol class="actions-list">{items}</ol>
</div>"""


def build_html(galleries: List[Gallery], events_rows, resources_rows, actions_rows) -> str:
    regions = sorted(set(g.region for g in galleries if not g.excluded))
    region_opts = "\n".join(f'<option value="{r}">{r}</option>' for r in regions)

    cards = "\n".join(gallery_card(g) for g in galleries)
    events_html = events_table(events_rows)
    actions_html = actions_list(actions_rows)

    total = sum(1 for g in galleries if not g.excluded)
    open_count = sum(1 for g in galleries if not g.excluded and g.open_call == "open")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bay Area Gallery Database</title>
<style>
  :root {{
    --bg: #0f0f13;
    --surface: #1a1a22;
    --surface2: #22222e;
    --border: #2e2e3e;
    --accent: #7c6af7;
    --accent2: #5de6c8;
    --green: #3ecf7e;
    --red: #f05050;
    --text: #e8e8f0;
    --muted: #888899;
    --radius: 12px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }}

  /* ── Header ── */
  .hero {{
    background: linear-gradient(135deg, #1a1230 0%, #0f1a2e 100%);
    border-bottom: 1px solid var(--border);
    padding: 48px 24px 32px;
    text-align: center;
  }}
  .hero h1 {{
    font-size: clamp(1.6rem, 4vw, 2.6rem);
    font-weight: 700;
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 10px;
  }}
  .hero p {{ color: var(--muted); font-size: 0.95rem; margin-bottom: 20px; }}
  .stats {{
    display: inline-flex;
    gap: 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 99px;
    padding: 8px 24px;
    font-size: 0.85rem;
  }}
  .stat-item {{ display: flex; align-items: center; gap: 6px; }}
  .stat-num {{ font-weight: 700; color: var(--accent2); }}

  /* ── Filters ── */
  .filters {{
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(15,15,19,0.92);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .search-input {{
    flex: 1;
    min-width: 180px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 8px 14px;
    font-size: 0.9rem;
    outline: none;
    transition: border-color 0.2s;
  }}
  .search-input:focus {{ border-color: var(--accent); }}
  .filter-select {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 8px 12px;
    font-size: 0.85rem;
    cursor: pointer;
    outline: none;
  }}
  .filter-btn {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--muted);
    padding: 8px 14px;
    font-size: 0.85rem;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
  }}
  .filter-btn:hover, .filter-btn.active {{
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }}
  #count-display {{
    color: var(--muted);
    font-size: 0.82rem;
    margin-left: auto;
    white-space: nowrap;
  }}

  /* ── Grid ── */
  .main {{ max-width: 1400px; margin: 0 auto; padding: 28px 20px 60px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
    margin-bottom: 48px;
  }}

  /* ── Cards ── */
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 18px 16px;
    transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .card:hover {{
    transform: translateY(-2px);
    border-color: var(--accent);
    box-shadow: 0 8px 30px rgba(124,106,247,0.12);
  }}
  .card[data-open="open"] {{ border-left: 3px solid var(--green); }}
  .card[data-blue="true"] {{ border-left: 3px solid #6ba3f5; }}

  .card-header {{ display: flex; flex-direction: column; gap: 6px; }}
  .card-title-row {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
  }}
  .card-name {{
    font-size: 0.97rem;
    font-weight: 600;
    color: var(--text);
    line-height: 1.3;
  }}
  .card-badges {{ display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; flex-shrink: 0; }}
  .gallery-url {{
    font-size: 0.78rem;
    color: var(--accent);
    text-decoration: none;
    opacity: 0.85;
    transition: opacity 0.15s;
  }}
  .gallery-url:hover {{ opacity: 1; }}

  .card-body {{ display: flex; flex-direction: column; gap: 6px; font-size: 0.83rem; }}
  .gallery-addr {{ color: var(--muted); }}
  .gallery-desc {{ color: #aab; line-height: 1.45; }}
  .gallery-note {{ color: var(--muted); font-style: italic; line-height: 1.4; }}
  .gallery-event {{
    background: var(--surface2);
    border-radius: 6px;
    padding: 6px 10px;
    color: var(--accent2);
    font-size: 0.8rem;
    line-height: 1.4;
  }}

  /* ── Badges ── */
  .badge {{
    font-size: 0.7rem;
    padding: 2px 7px;
    border-radius: 99px;
    font-weight: 600;
    white-space: nowrap;
  }}
  .badge-green {{ background: rgba(62,207,126,0.15); color: var(--green); border: 1px solid rgba(62,207,126,0.3); }}
  .badge-red   {{ background: rgba(240,80,80,0.1);  color: var(--red);   border: 1px solid rgba(240,80,80,0.25); }}
  .badge-blue  {{ background: rgba(107,163,245,0.12); color: #6ba3f5;    border: 1px solid rgba(107,163,245,0.3); }}
  .badge-gray  {{ background: rgba(136,136,153,0.15); color: var(--muted); border: 1px solid var(--border); }}

  /* ── Events table ── */
  .events-section {{ margin-bottom: 40px; }}
  .events-section h2 {{ font-size: 1.1rem; margin-bottom: 14px; color: var(--text); }}
  .events-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
  }}
  .events-table th {{
    background: var(--surface2);
    color: var(--muted);
    font-weight: 600;
    padding: 10px 14px;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }}
  .events-table td {{
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  .events-table tr:hover td {{ background: var(--surface2); }}

  /* ── Actions ── */
  .actions-section {{ margin-bottom: 48px; }}
  .actions-section h2 {{ font-size: 1.1rem; margin-bottom: 14px; color: var(--text); }}
  .actions-list {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 16px 16px 40px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    font-size: 0.9rem;
    line-height: 1.5;
    color: #ccd;
  }}

  /* ── Card footer ── */
  .card-footer {{
    display: flex;
    justify-content: flex-end;
    padding-top: 8px;
    border-top: 1px solid var(--border);
    margin-top: 4px;
  }}
  .apply-btn {{
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--accent2);
    text-decoration: none;
    padding: 5px 12px;
    border: 1px solid rgba(93,230,200,0.3);
    border-radius: 6px;
    transition: all 0.15s;
  }}
  .apply-btn:hover {{
    background: rgba(93,230,200,0.1);
    border-color: var(--accent2);
  }}

  /* ── Hidden ── */
  .card.hidden {{ display: none; }}

  /* ── Footer ── */
  .footer {{
    text-align: center;
    color: var(--muted);
    font-size: 0.78rem;
    padding: 32px 24px;
    border-top: 1px solid var(--border);
  }}
  .footer a {{ color: var(--accent); text-decoration: none; }}
</style>
</head>
<body>

<div class="hero">
  <div class="hero-brand"><a href="https://naaaaaaqi.github.io/human-artark/" style="color:var(--accent2);text-decoration:none;font-size:0.85rem;letter-spacing:0.08em;">← Human ArtArk</a></div>
  <h1>Bay Area Gallery Database</h1>
  <p>San Francisco · East Bay · Peninsula · South Bay · Santa Cruz · North Bay</p>
  <div class="stats">
    <div class="stat-item">🏛 <span class="stat-num">{total}</span> galleries</div>
    <div class="stat-item">🟢 <span class="stat-num">{open_count}</span> open calls</div>
    <div class="stat-item">📅 Updated <span class="stat-num">{TODAY}</span></div>
  </div>
</div>

<div class="filters">
  <input class="search-input" type="search" id="search" placeholder="Search galleries, addresses…" />
  <select class="filter-select" id="region-filter">
    <option value="">All regions</option>
    {region_opts}
  </select>
  <button class="filter-btn active" data-filter="all">All</button>
  <button class="filter-btn" data-filter="open">🟢 Open Call</button>
  <button class="filter-btn" data-filter="stars3">⭐⭐⭐ Top picks</button>
  <button class="filter-btn" data-filter="bluechip">🔵 Blue-chip</button>
  <span id="count-display"></span>
</div>

<div class="main">
  <div class="grid" id="gallery-grid">
    {cards}
  </div>
  {events_html}
  {actions_html}
</div>

<div class="footer">
  Last updated {TODAY} · Curated by hand + AI-assisted status detection ·
  <a href="https://github.com/NaaaaaaQi/my-gallery-agent" target="_blank">GitHub ↗</a>
</div>

<script>
const grid    = document.getElementById('gallery-grid');
const search  = document.getElementById('search');
const region  = document.getElementById('region-filter');
const counter = document.getElementById('count-display');
const btns    = document.querySelectorAll('.filter-btn');
let activeFilter = 'all';

function applyFilters() {{
  const q   = search.value.toLowerCase();
  const reg = region.value;
  let visible = 0;

  grid.querySelectorAll('.card').forEach(card => {{
    const text   = card.textContent.toLowerCase();
    const open   = card.dataset.open;
    const stars  = parseInt(card.dataset.stars);
    const blue   = card.dataset.blue === 'true';
    const cRegion = card.dataset.region;

    const matchQ      = !q || text.includes(q);
    const matchRegion = !reg || cRegion === reg;
    const matchFilter =
      activeFilter === 'all'     ? true :
      activeFilter === 'open'    ? open === 'open' :
      activeFilter === 'stars3'  ? stars === 3 :
      activeFilter === 'bluechip'? blue :
      true;

    const show = matchQ && matchRegion && matchFilter;
    card.classList.toggle('hidden', !show);
    if (show) visible++;
  }});

  counter.textContent = visible + ' results';
}}

search.addEventListener('input', applyFilters);
region.addEventListener('change', applyFilters);

btns.forEach(btn => {{
  btn.addEventListener('click', () => {{
    btns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.filter;
    applyFilters();
  }});
}});

applyFilters();
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(DB_PATH):
        sys.exit(f"Error: {DB_PATH} not found")

    md_text = open(DB_PATH).read()
    galleries, events_rows, resources_rows, actions_rows = parse_db(md_text)

    os.makedirs(OUT_DIR, exist_ok=True)
    html = build_html(galleries, events_rows, resources_rows, actions_rows)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    total   = sum(1 for g in galleries if not g.excluded)
    open_ct = sum(1 for g in galleries if not g.excluded and g.open_call == "open")
    print(f"✓  Generated {OUT_PATH}")
    print(f"   {total} galleries  |  {open_ct} open calls")


if __name__ == "__main__":
    main()
