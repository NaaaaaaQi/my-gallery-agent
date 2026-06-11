#!/usr/bin/env python3
"""
Bay Area Gallery Open Call Status Updater

Scrapes each gallery's website, uses Claude to detect open calls and
upcoming events, then rewrites GALLERY_DATABASE.md with updated statuses.

Usage:
    python3 update_gallery_status.py [--dry-run] [--gallery "Gallery Name"]

Environment:
    ANTHROPIC_API_KEY  required
"""

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import httpx
from anthropic import Anthropic
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

WORKSPACE_CONTAINER = "openclaw-gateway"
DB_PATH = os.path.expanduser("~/projects/openclaw/GALLERY_DATABASE.md")
TODAY = date.today().isoformat()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

FETCH_TIMEOUT = 12          # seconds per request
RATE_LIMIT_DELAY = 1.5      # seconds between requests
MAX_PAGE_CHARS = 6000       # chars sent to Claude per gallery

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Gallery:
    name: str
    url: str                          # bare domain, e.g. "arc-sf.com"
    block_start: int                  # line index in the markdown
    block_end: int
    original_lines: list[str]

@dataclass
class StatusResult:
    gallery: Gallery
    open_call: Optional[bool]         # True / False / None (couldn't determine)
    events: List[str] = field(default_factory=list)
    notes: str = ""
    fetch_error: str = ""

# ── Markdown parser ───────────────────────────────────────────────────────────

URL_RE = re.compile(r"网址.*?[:\|]\s*(?:\[.*?\]\(https?://)?([a-z0-9.\-]+\.[a-z]{2,})", re.I)
OPEN_CALL_RE = re.compile(r"Open Call.*?(🟢|🔴)", re.I)
NAME_RE = re.compile(r"^###\s+(.+)")


def parse_galleries(md_text: str) -> List[Gallery]:
    """Extract gallery entries that have a URL from the markdown."""
    lines = md_text.splitlines()
    galleries = []
    i = 0
    while i < len(lines):
        name_match = NAME_RE.match(lines[i])
        if not name_match:
            i += 1
            continue

        name = name_match.group(1).strip()
        # strip emoji / rating suffixes
        name = re.sub(r"[⭐🔵🔴🟢⚠️✅❌📧]+", "", name).strip()

        block_start = i
        # scan ahead to find the url and end of block
        url = None
        j = i + 1
        while j < len(lines):
            if NAME_RE.match(lines[j]) or lines[j].startswith("## "):
                break
            m = URL_RE.search(lines[j])
            if m and not url:
                url = m.group(1).lower().strip("/")
            j += 1

        block_end = j
        if url and "待确认" not in url and "待深入" not in url:
            galleries.append(Gallery(
                name=name,
                url=url,
                block_start=block_start,
                block_end=block_end,
                original_lines=lines[block_start:block_end],
            ))
        i = block_end

    return galleries


# ── Web fetcher ───────────────────────────────────────────────────────────────

SUBMISSION_PATHS = [
    "/",
    "/submissions", "/submit", "/calls", "/call-for-entry",
    "/call-for-artists", "/open-call", "/opportunities",
    "/for-artists", "/artists",
]


def fetch_page_text(base_url: str) -> "tuple[str, str]":
    """
    Try the base URL plus common submission sub-paths.
    Returns (combined_text, error_message).
    """
    collected = []
    last_error = ""

    with httpx.Client(headers=HEADERS, timeout=FETCH_TIMEOUT,
                      follow_redirects=True) as client:
        for path in SUBMISSION_PATHS[:4]:   # limit to first 4 to be polite
            url = f"https://{base_url}{path}"
            try:
                r = client.get(url)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "html.parser")
                    # remove nav / footer noise
                    for tag in soup(["nav", "footer", "script", "style"]):
                        tag.decompose()
                    text = soup.get_text(separator=" ", strip=True)
                    collected.append(text[:3000])
                time.sleep(0.4)
            except Exception as e:
                last_error = str(e)

    combined = " ".join(collected)[:MAX_PAGE_CHARS]
    return combined, ("" if collected else last_error)


# ── Claude analysis ───────────────────────────────────────────────────────────

def analyze_with_claude(client: Anthropic, gallery_name: str, page_text: str) -> dict:
    """
    Ask Claude Haiku to extract open-call status and events from page text.
    Returns dict: {open_call: bool, events: [str], notes: str}
    """
    if not page_text.strip():
        return {"open_call": None, "events": [], "notes": "No page content fetched"}

    prompt = f"""You are analyzing the website of an art gallery called "{gallery_name}".

Here is the text scraped from their website:
---
{page_text}
---

Answer these questions in JSON format only (no markdown, no explanation):
{{
  "open_call": true/false/null,   // true = actively accepting submissions right now, false = not currently, null = cannot determine
  "deadline": "YYYY-MM-DD or null",  // submission deadline if mentioned
  "events": ["short description of upcoming event with date if found"],  // list, max 3 items, empty if none
  "notes": "one sentence summary of what you found relevant to an artist"
}}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        import json
        return json.loads(raw)
    except Exception as e:
        return {"open_call": None, "events": [], "notes": f"Claude error: {e}"}


# ── Markdown updater ──────────────────────────────────────────────────────────

def update_gallery_block(lines: List[str], result: StatusResult) -> List[str]:
    """Rewrite the open-call line and append new event info in the block."""
    updated = []
    for line in lines:
        # update 🟢/🔴
        if re.search(r"Open Call.*?(🟢|🔴)", line, re.I) and result.open_call is not None:
            new_emoji = "🟢" if result.open_call else "🔴"
            line = re.sub(r"(🟢|🔴)", new_emoji, line)

        # update 近期活动 line if we found new events
        if result.events and "近期活动" in line:
            events_str = "；".join(result.events[:2])
            line = re.sub(r"\|([^|]+)$", f"| {events_str} |", line)

        updated.append(line)

    return updated


def rewrite_database(md_text: str, results: List[StatusResult]) -> str:
    lines = md_text.splitlines()

    # process in reverse order so line indices stay valid
    for result in sorted(results, key=lambda r: r.gallery.block_start, reverse=True):
        if result.fetch_error and result.open_call is None:
            continue  # skip galleries we couldn't reach
        new_block = update_gallery_block(result.gallery.original_lines, result)
        lines[result.gallery.block_start:result.gallery.block_end] = new_block

    # update the "最后更新" datestamp at the top
    updated = "\n".join(lines)
    updated = re.sub(
        r"最后更新：\d{4}-\d{2}-\d{2}",
        f"最后更新：{TODAY}",
        updated,
    )
    return updated


# ── Report printer ────────────────────────────────────────────────────────────

def print_report(results: List[StatusResult]):
    changed = [r for r in results if r.open_call is not None and not r.fetch_error]
    errors  = [r for r in results if r.fetch_error]

    print(f"\n{'─'*60}")
    print(f"  Gallery Status Update — {TODAY}")
    print(f"{'─'*60}")

    newly_open   = [r for r in changed if r.open_call]
    newly_closed = [r for r in changed if not r.open_call]

    if newly_open:
        print(f"\n🟢  OPEN CALL DETECTED ({len(newly_open)})")
        for r in newly_open:
            print(f"    • {r.gallery.name}")
            if r.events:
                for e in r.events:
                    print(f"        → {e}")
            if r.notes:
                print(f"        ℹ {r.notes}")

    if newly_closed:
        print(f"\n🔴  NO ACTIVE CALL ({len(newly_closed)})")
        for r in newly_closed:
            print(f"    • {r.gallery.name}  —  {r.notes or 'no submission info found'}")

    if errors:
        print(f"\n⚠️   FETCH ERRORS ({len(errors)})")
        for r in errors:
            print(f"    • {r.gallery.name}: {r.fetch_error[:80]}")

    print(f"\n    Total checked: {len(results)}  |  Updated: {len(changed)}  |  Errors: {len(errors)}")
    print(f"{'─'*60}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Update Bay Area gallery open call statuses")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report but don't write files")
    parser.add_argument("--gallery", metavar="NAME",
                        help="Only check galleries whose name contains this string")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable not set")

    client = Anthropic(api_key=api_key)

    if not os.path.exists(DB_PATH):
        sys.exit(f"Error: database not found at {DB_PATH}")

    md_text = open(DB_PATH).read()
    galleries = parse_galleries(md_text)

    if args.gallery:
        galleries = [g for g in galleries if args.gallery.lower() in g.name.lower()]
        if not galleries:
            sys.exit(f"No gallery found matching '{args.gallery}'")

    # skip blue-chip / ❌ galleries (邀请制 only, waste of requests)
    skip_keywords = ["❌", "不接受投稿", "排除"]
    galleries = [
        g for g in galleries
        if not any(kw in "\n".join(g.original_lines) for kw in skip_keywords)
    ]

    print(f"Checking {len(galleries)} galleries...")

    results = []
    for i, gallery in enumerate(galleries, 1):
        print(f"  [{i}/{len(galleries)}] {gallery.name} ({gallery.url})", end=" ", flush=True)

        page_text, error = fetch_page_text(gallery.url)

        if error and not page_text:
            print("✗ fetch failed")
            results.append(StatusResult(
                gallery=gallery, open_call=None, fetch_error=error
            ))
        else:
            analysis = analyze_with_claude(client, gallery.name, page_text)
            print("✓")
            results.append(StatusResult(
                gallery=gallery,
                open_call=analysis.get("open_call"),
                events=analysis.get("events", []),
                notes=analysis.get("notes", ""),
            ))

        time.sleep(RATE_LIMIT_DELAY)

    print_report(results)

    if args.dry_run:
        print("Dry run — no files written.")
        return

    # write updated markdown
    updated_md = rewrite_database(md_text, results)
    with open(DB_PATH, "w") as f:
        f.write(updated_md)
    print(f"✓ Updated {DB_PATH}")

    # sync into running Docker container
    try:
        subprocess.run(
            ["docker", "cp", DB_PATH,
             f"{WORKSPACE_CONTAINER}:/workspace/GALLERY_DATABASE.md"],
            check=True, capture_output=True,
        )
        print(f"✓ Synced to Docker container '{WORKSPACE_CONTAINER}'")
    except subprocess.CalledProcessError as e:
        print(f"⚠  docker cp failed (is the container running?): {e.stderr.decode()}")

    print("\nDone. The agent will use the updated database on the next conversation.")


if __name__ == "__main__":
    main()
