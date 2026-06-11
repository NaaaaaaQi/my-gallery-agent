#!/usr/bin/env python3
"""
Newsletter parser: reads wualex561@gmail.com via IMAP, extracts open call
info from gallery newsletters using Claude, and updates GALLERY_DATABASE.md.

Usage:
    python3 scripts/parse_newsletters.py [--dry-run]

Reads credentials from .env in the project root.
"""

import argparse
import email
import imaplib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from email.header import decode_header
from pathlib import Path

from anthropic import Anthropic

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
ENV_PATH     = PROJECT_ROOT / ".env"
DB_PATH      = PROJECT_ROOT / "GALLERY_DATABASE.md"
PROCESSED_PATH = PROJECT_ROOT / ".processed_emails"  # tracks seen message IDs
CONTAINER    = "openclaw-gateway"
TODAY        = date.today().isoformat()

IMAP_HOST    = "imap.gmail.com"
LOOKBACK_DAYS = 30   # only read emails from last 30 days

MAX_EMAIL_CHARS = 8000

# ── Env loader ────────────────────────────────────────────────────────────────

def load_env():
    if not ENV_PATH.exists():
        sys.exit(f"Error: {ENV_PATH} not found. Create it with ANTHROPIC_API_KEY, GALLERY_EMAIL, GALLERY_EMAIL_PASSWORD.")
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── Processed email tracker ───────────────────────────────────────────────────

def load_processed() -> set:
    if PROCESSED_PATH.exists():
        return set(PROCESSED_PATH.read_text().splitlines())
    return set()

def save_processed(ids: set):
    PROCESSED_PATH.write_text("\n".join(sorted(ids)))

# ── IMAP reader ───────────────────────────────────────────────────────────────

def decode_str(s):
    if s is None:
        return ""
    parts = decode_header(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def get_email_text(msg) -> str:
    """Extract plain text from an email message."""
    text_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try:
                    text_parts.append(part.get_payload(decode=True).decode("utf-8", errors="replace"))
                except Exception:
                    pass
            elif ct == "text/html" and not text_parts:
                try:
                    from bs4 import BeautifulSoup
                    html = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    soup = BeautifulSoup(html, "html.parser")
                    for tag in soup(["script", "style", "nav", "footer"]):
                        tag.decompose()
                    text_parts.append(soup.get_text(separator=" ", strip=True))
                except Exception:
                    pass
    else:
        try:
            text_parts.append(msg.get_payload(decode=True).decode("utf-8", errors="replace"))
        except Exception:
            pass
    return " ".join(text_parts)[:MAX_EMAIL_CHARS]


def fetch_newsletters(email_addr: str, password: str) -> list[dict]:
    """Connect via IMAP and return list of {id, subject, sender, body, date}."""
    since = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")

    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(email_addr, password)
    mail.select("inbox")

    _, data = mail.search(None, f'(SINCE "{since}")')
    msg_ids = data[0].split()
    print(f"  Found {len(msg_ids)} emails in the last {LOOKBACK_DAYS} days")

    messages = []
    for mid in msg_ids:
        _, raw = mail.fetch(mid, "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])
        messages.append({
            "id": mid.decode(),
            "subject": decode_str(msg.get("Subject", "")),
            "sender":  decode_str(msg.get("From", "")),
            "date":    msg.get("Date", ""),
            "body":    get_email_text(msg),
        })

    mail.logout()
    return messages

# ── Claude analysis ───────────────────────────────────────────────────────────

def analyze_email(client: Anthropic, msg: dict) -> dict:
    prompt = f"""You received a newsletter or email from a gallery or arts organization.

From: {msg['sender']}
Subject: {msg['subject']}
Date: {msg['date']}

Body:
---
{msg['body']}
---

Extract any actionable information for an emerging visual artist. Return JSON only:
{{
  "gallery_name": "name of the gallery/org or null",
  "has_open_call": true/false,
  "deadline": "YYYY-MM-DD or null",
  "call_description": "one sentence describing what they're looking for, or null",
  "events": ["upcoming event with date if mentioned"],
  "relevant": true/false
}}

Set relevant=false if this is a purely commercial email, spam, or unrelated to art submissions/events."""

    try:
        msg_resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg_resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        return {"gallery_name": None, "has_open_call": False, "relevant": False, "error": str(e)}

# ── Database updater ──────────────────────────────────────────────────────────

def update_database(findings: list[dict]) -> bool:
    """Inject newsletter-sourced open call info into GALLERY_DATABASE.md."""
    if not findings:
        return False

    md = DB_PATH.read_text()
    changed = False

    for f in findings:
        if not f.get("gallery_name") or not f.get("has_open_call"):
            continue

        name = f["gallery_name"]
        # find the gallery section (fuzzy: check if name words appear in a ### heading)
        name_words = [w.lower() for w in name.split() if len(w) > 3]
        lines = md.splitlines()

        for i, line in enumerate(lines):
            if not line.startswith("### "):
                continue
            heading_low = line.lower()
            if any(w in heading_low for w in name_words):
                # update or add Open Call line
                for j in range(i+1, min(i+20, len(lines))):
                    if "open call" in lines[j].lower():
                        if "🔴" in lines[j]:
                            lines[j] = lines[j].replace("🔴", "🟢")
                            desc = f.get("call_description", "")
                            deadline = f.get("deadline", "")
                            suffix = ""
                            if deadline:
                                suffix += f" 截止 {deadline}"
                            if desc:
                                suffix += f"；{desc}"
                            if suffix:
                                lines[j] = lines[j].rstrip() + suffix
                            changed = True
                        break
                break

    if changed:
        # update datestamp
        updated = re.sub(r"最后更新：\d{4}-\d{2}-\d{2}", f"最后更新：{TODAY}", "\n".join(lines))
        DB_PATH.write_text(updated)

    return changed

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env()
    api_key   = os.environ.get("ANTHROPIC_API_KEY")
    gmail     = os.environ.get("GALLERY_EMAIL")
    gmail_pwd = os.environ.get("GALLERY_EMAIL_PASSWORD")

    if not all([api_key, gmail, gmail_pwd]):
        sys.exit("Error: missing ANTHROPIC_API_KEY, GALLERY_EMAIL, or GALLERY_EMAIL_PASSWORD in .env")

    client = Anthropic(api_key=api_key)
    processed = load_processed()

    print(f"Connecting to {gmail}…")
    messages = fetch_newsletters(gmail, gmail_pwd)

    new_msgs = [m for m in messages if m["id"] not in processed]
    print(f"  {len(new_msgs)} unprocessed emails")

    if not new_msgs:
        print("Nothing new. Done.")
        return

    findings = []
    for i, msg in enumerate(new_msgs, 1):
        print(f"  [{i}/{len(new_msgs)}] {msg['subject'][:60]}", end=" ", flush=True)
        result = analyze_email(client, msg)
        if result.get("relevant"):
            print(f"✓  open_call={result.get('has_open_call')}  gallery={result.get('gallery_name')}")
            findings.append(result)
        else:
            print("– skipped")

    # report
    open_calls = [f for f in findings if f.get("has_open_call")]
    print(f"\n{'─'*50}")
    print(f"  Newsletter scan — {TODAY}")
    print(f"{'─'*50}")
    if open_calls:
        print(f"\n🟢  Open calls found ({len(open_calls)}):")
        for f in open_calls:
            print(f"    • {f['gallery_name']}")
            if f.get("deadline"):
                print(f"        Deadline: {f['deadline']}")
            if f.get("call_description"):
                print(f"        {f['call_description']}")
            for e in f.get("events", []):
                print(f"        → {e}")
    else:
        print("\n  No open calls found in new emails.")
    print(f"{'─'*50}\n")

    if args.dry_run:
        print("Dry run — no files written.")
        return

    # update database
    if update_database(findings):
        print("✓ Updated GALLERY_DATABASE.md")

        # regenerate HTML
        subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/generate_html.py")], check=True)
        print("✓ Regenerated docs/index.html")

        # sync to Docker
        try:
            subprocess.run(
                ["docker", "cp", str(DB_PATH), f"{CONTAINER}:/workspace/GALLERY_DATABASE.md"],
                check=True, capture_output=True,
            )
            print(f"✓ Synced to Docker container '{CONTAINER}'")
        except subprocess.CalledProcessError:
            print("⚠  docker cp failed (container not running?)")

        # git push
        subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "add", "GALLERY_DATABASE.md", "docs/index.html"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "commit",
             "-m", f"Newsletter update {TODAY}: {len(open_calls)} open call(s)"],
            check=True,
        )
        subprocess.run(["git", "-C", str(PROJECT_ROOT), "push"], check=True)
        print("✓ Pushed to GitHub")
    else:
        print("No database changes needed.")

    # mark all as processed
    save_processed(processed | {m["id"] for m in new_msgs})
    print(f"✓ Marked {len(new_msgs)} emails as processed")


if __name__ == "__main__":
    main()
