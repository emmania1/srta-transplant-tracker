#!/usr/bin/env python3
"""Fetch transplant-industry news via Google News RSS, one query per keyword group.

Reads config/keywords.json, merges with data/processed/news.json, dedupes by URL
and near-identical headline, keeps `lookback_days` (default 90), newest first.
Each item remembers when the tracker first saw it (first_seen) so the weekly
digest can count genuinely new items.
"""
import difflib
import email.utils
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "keywords.json"
OUT = ROOT / "data" / "processed" / "news.json"
SOURCE = "Google News RSS search (news.google.com/rss/search)"
SIMILARITY = 0.9


def build_query(terms):
    parts = [f'"{t}"' if " " in t else t for t in terms]
    return " OR ".join(parts)


def make_filter(cfg):
    blocked = {b.lower() for b in cfg.get("blocked_sources", [])}
    pats = [re.compile(x, re.I) for x in cfg.get("exclude_title_patterns", [])]

    def keep(item):
        src = item["source"].lower()
        if any(b in src for b in blocked):
            return False
        return not any(p.search(item["headline"]) for p in pats)
    return keep


def fetch_group(group, days):
    q = f"({build_query(group['terms'])}) when:{days}d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (srta-tracker)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    items = []
    require = [s.lower() for s in group.get("require_any", [])]
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        src_el = it.find("source")
        source = src_el.text.strip() if src_el is not None and src_el.text else ""
        desc = it.findtext("description") or ""
        if not title or not link or not pub:
            continue
        # Google appends " - Publisher" to titles; strip it for display/dedupe.
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)].strip()
        if require and not any(s in (title + " " + desc).lower() for s in require):
            continue
        dt = email.utils.parsedate_to_datetime(pub).astimezone(timezone.utc)
        items.append({
            "headline": title,
            "source": source,
            "date": dt.isoformat(timespec="seconds"),
            "url": link,
            "tags": [group["id"]],
        })
    return items


def norm_headline(h):
    return re.sub(r"[^a-z0-9 ]", "", h.lower()).strip()


def merge(existing, fresh):
    """Merge fresh items into existing; union tags on duplicates."""
    out = list(existing)
    for item in fresh:
        nh = norm_headline(item["headline"])
        match = None
        for e in out:
            if e["url"] == item["url"]:
                match = e
                break
            en = norm_headline(e["headline"])
            if en == nh or (abs(len(en) - len(nh)) < 25 and
                            difflib.SequenceMatcher(None, en, nh).ratio() >= SIMILARITY):
                match = e
                break
        if match:
            match["tags"] = sorted(set(match["tags"]) | set(item["tags"]))
        else:
            out.append(item)
    return out


def main():
    cfg = json.loads(CONFIG.read_text())
    days = int(cfg.get("lookback_days", 90))
    now = datetime.now(timezone.utc)
    prev = json.loads(OUT.read_text()) if OUT.exists() else {"items": []}
    items = prev.get("items", [])

    errors = []
    fresh_all = []
    for g in cfg["groups"]:
        try:
            got = fetch_group(g, days)
            print(f"{g['id']}: {len(got)} items")
            fresh_all.extend(got)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{g['id']}: {e}")
            print(f"{g['id']}: FAILED {e}", file=sys.stderr)

    stamp = now.isoformat(timespec="seconds")
    for f in fresh_all:
        f["first_seen"] = stamp
    keep = make_filter(cfg)
    items = merge([i for i in items if keep(i)], [f for f in fresh_all if keep(f)])

    cutoff = now - timedelta(days=days)
    items = [i for i in items if datetime.fromisoformat(i["date"]) >= cutoff]
    items.sort(key=lambda i: i["date"], reverse=True)

    out = {
        "source": SOURCE,
        "tag": "Live",
        "fetched_at": stamp if fresh_all or not errors else prev.get("fetched_at"),
        "lookback_days": days,
        "groups": [{"id": g["id"], "label": g["label"]} for g in cfg["groups"]],
        "errors": errors,
        "items": items,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"news.json: {len(items)} items kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
