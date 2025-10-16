import os
import json
import time
import random
from datetime import datetime, timezone
import requests
import feedparser

FEED_URL = "https://www.golfpost.de/-/marcel-schneider/feed/"
STATE_FILE = "known_ids.json"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
UA = {"User-Agent": "github-action-golfpost-marcel-discord"}

# Optionales Verhalten ohne Codeänderung steuerbar
# Wenn du beim allerersten Lauf trotz Baseline einen Startpost willst, setze im Repo-Secret POST_ON_INIT=true
POST_ON_INIT = os.environ.get("POST_ON_INIT", "").lower() in {"1", "true", "yes"}

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f).get("ids", []))
        except Exception:
            return set()
    return set()

def save_state(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(list(ids))}, f, ensure_ascii=False, indent=2)

def fetch_feed():
    etag = None
    modified = None
    if os.path.exists(".etag"):
        with open(".etag", "r", encoding="utf-8") as f:
            etag = f.read().strip() or None
    if os.path.exists(".lastmod"):
        with open(".lastmod", "r", encoding="utf-8") as f:
            modified = f.read().strip() or None

    d = feedparser.parse(FEED_URL, etag=etag, modified=modified)
    # 304 bedeutet keine Änderung
    if getattr(d, "status", 200) == 304:
        return d

    # ETag und Last-Modified aktualisieren
    if d.get("etag"):
        with open(".etag", "w", encoding="utf-8") as f:
            f.write(d.etag)
    if d.get("modified"):
        try:
            with open(".lastmod", "w", encoding="utf-8") as f:
                f.write(time.strftime("%a, %d %b %Y %H:%M:%S GMT", d.modified))
        except Exception:
            pass
    return d

def build_embed(title, url, summary, published):
    ts = None
    if published:
        try:
            ts = datetime(*published[:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            ts = datetime.now(timezone.utc).isoformat()

    if summary:
        summary = summary.strip()
    if summary and len(summary) > 300:
        summary = summary[:297] + "..."

    return {
        "title": title or "Neuer Artikel",
        "url": url or "",
        "description": summary or "",
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Golfpost Marcel Schneider"},
    }

def post_discord(payload):
    if not DISCORD_WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK fehlt")
    backoff = 5
    for _ in range(6):
        r = requests.post(DISCORD_WEBHOOK, json=payload, headers=UA, timeout=20)
        # Discord antwortet 204 bei Erfolg
        if r.status_code == 204 or (200 <= r.status_code < 300):
            return
        if r.status_code == 429:
            retry = r.headers.get("Retry-After")
            wait_s = float(retry) if retry else backoff
            time.sleep(wait_s)
            backoff = min(backoff * 2, 300)
            continue
        if r.status_code in (502, 503, 504):
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
            continue
        r.raise_for_status()
    raise RuntimeError("Discord Webhook dauerhaft fehlgeschlagen")

def init_baseline_if_needed(feed):
    # Legt Baseline an, wenn STATE_FILE fehlt
    if os.path.exists(STATE_FILE):
        return False  # keine Baseline nötig
    ids
