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

def state_exists() -> bool:
    return os.path.exists(STATE_FILE)

def load_state():
    if state_exists():
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

    # Etags und Last-Modified aktualisieren, damit beim Initiallauf Dateien entstehen
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
        if len(summary) > 300:
            summary = summary[:297] + "..."

    embed = {
        "title": title or "Neuer Artikel",
        "url": url or "",
        "description": summary or "",
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Golfpost Marcel Schneider"},
    }
    return embed

def post_discord(payload):
    if not DISCORD_WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK fehlt")
    backoff = 5
    for _ in range(6):
        r = requests.post(DISCORD_WEBHOOK, json=payload, headers=UA, timeout=20)
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

def main():
    # Jitter gegen gleichzeitige Ausführungen
    time.sleep(random.randint(0, 120))

    first_run = not state_exists()
    known = load_state()

    feed = fetch_feed()
    entries = feed.get("entries", [])

    # Beim ersten Lauf Baseline setzen ohne alte Artikel zu posten
    if first_run:
        ids = []
        for e in entries:
            guid = e.get("id") or e.get("guid") or e.get("link")
            if guid:
                ids.append(guid)
        save_state(set(ids))
        # kurze Bestätigung in Discord, damit du siehst, dass der Monitor aktiv ist
        try:
            post_discord({"content": f"Monitor aktiv. Baseline gesetzt mit {len(ids)} Artikeln."})
        except Exception:
            # Falls kein Webhook gesetzt ist oder blockiert wurde, soll der Lauf trotzdem sauber enden
            pass
        print(f"Baseline gesetzt mit {len(ids)} Artikeln.")
        return

    # Normalbetrieb
    new_items = []
    for e in entries:
        guid = e.get("id") or e.get("guid") or e.get("link")
        if not guid or guid in known:
            continue
        title = e.get("title")
        url = e.get("link") or ""
        summary = e.get("summary") or e.get("subtitle")
        published = e.get("published_parsed")
        new_items.append((guid, title, url, summary, published))

    # Neueste zuerst posten
    new_items.sort(key=lambda x: x[4] or 0, reverse=True)

    for guid, title, url, summary, published in new_items:
        embed = build_embed(title, url, summary, published)
        payload = {
            "content": "Neue Golfpost News zu Marcel Schneider",
            "embeds": [embed],
        }
        post_discord(payload)
        known.add(guid)
        time.sleep(1)

    if new_items:
        save_state(known)
        print(f"{len(new_items)} neue Artikel gepostet.")
    else:
        print("Keine neuen Artikel.")

if __name__ == "__main__":
    main()
