import os
import json
import time
from datetime import datetime, timezone
import requests
import feedparser

FEED_URL = "https://www.golfpost.de/-/marcel-schneider/feed/"
STATE_FILE = "known_ids.json"
TEAMS_WEBHOOK = os.environ.get("TEAMS_WEBHOOK")
HEADERS = {"User-Agent": "github-action-golfpost-marcel-schneider-monitor"}

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return set(data.get("ids", []))
            except Exception:
                return set()
    return set()

def save_state(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(list(ids))}, f, ensure_ascii=False, indent=2)

def fetch_feed():
    # ETag und Last-Modified verbessern Effizienz
    etag = None
    modified = None
    if os.path.exists(".etag"):
        with open(".etag", "r", encoding="utf-8") as f:
            etag = f.read().strip() or None
    if os.path.exists(".lastmod"):
        with open(".lastmod", "r", encoding="utf-8") as f:
            modified = f.read().strip() or None

    d = feedparser.parse(FEED_URL, etag=etag, modified=modified)
    # Status 304 bedeutet keine Änderungen
    if getattr(d, "status", 200) == 304:
        return d, etag, modified

    # Neue Etags sichern
    if d.get("etag"):
        with open(".etag", "w", encoding="utf-8") as f:
            f.write(d.etag)
    if d.get("modified"):
        with open(".lastmod", "w", encoding="utf-8") as f:
            f.write(time.strftime("%a, %d %b %Y %H:%M:%S GMT", d.modified))
    return d, d.get("etag"), d.get("modified")

def make_card(title, url, summary, published):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary = (summary or "").strip()
    if len(summary) > 300:
        summary = summary[:297] + "..."
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": "Golf Post Update"},
                        {"type": "TextBlock", "wrap": True, "text": title},
                        {"type": "TextBlock", "isSubtle": True, "wrap": True, "spacing": "Small", "text": published or ""},
                        {"type": "TextBlock", "wrap": True, "text": summary}
                    ],
                    "actions": [
                        {"type": "Action.OpenUrl", "title": "Artikel öffnen", "url": url}
                    ]
                }
            }
        ],
        "text": f"Neue Marcel Schneider News gefunden am {ts}"
    }

def post_to_teams(payload):
    if not TEAMS_WEBHOOK:
        raise RuntimeError("TEAMS_WEBHOOK fehlt")
    r = requests.post(TEAMS_WEBHOOK, json=payload, headers=HEADERS, timeout=20)
    if r.status_code >= 300:
        raise RuntimeError(f"Teams Webhook Status {r.status_code} Body {r.text}")

def main():
    known = load_state()
    feed, _, _ = fetch_feed()
    entries = feed.get("entries", [])

    new_items = []
    for e in entries:
        guid = e.get("id") or e.get("guid") or e.get("link")
        if not guid:
            continue
        if guid in known:
            continue
        title = e.get("title") or "Neuer Artikel"
        url = e.get("link") or ""
        summary = e.get("summary") or e.get("subtitle") or ""
        published = ""
        if e.get("published"):
            published = e.published
        new_items.append((guid, title, url, summary, published))

    # Neueste zuerst in Teams
    new_items.sort(key=lambda x: x[4] or "", reverse=True)

    for guid, title, url, summary, published in new_items:
        card = make_card(title, url, summary, published)
        post_to_teams(card)
        known.add(guid)
        time.sleep(1)  # Rate Limit freundlich

    if new_items:
        save_state(known)

if __name__ == "__main__":
    main()
