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
import time
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
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124 Safari/537.36"}
MAX_RESOLVE_PER_RUN = 200


def resolve_google_url(gurl):
    """Google News RSS links are redirects (news.google.com/rss/articles/<id>). Decode to the
    publisher URL via the same two calls the Google News web page makes. Returns URL or raises."""
    if "news.google.com" not in gurl:
        return gurl
    aid = urllib.parse.urlparse(gurl).path.rsplit("/", 1)[-1]
    page = urllib.request.urlopen(urllib.request.Request(
        f"https://news.google.com/articles/{aid}?hl=en-US&gl=US&ceid=US:en", headers=BROWSER_UA), timeout=20
    ).read().decode("utf-8", "replace")
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not sg or not ts:
        raise ValueError("no decoding signature on article page")
    inner = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None,
                             None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
             aid, int(ts.group(1)), sg.group(1)]
    body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", json.dumps(inner), None, "generic"]]]))
    txt = urllib.request.urlopen(urllib.request.Request(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body.encode(),
        headers={**BROWSER_UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}), timeout=20
    ).read().decode()
    url = json.loads(json.loads(txt.split("\n\n", 1)[1])[:-2][0][2])[1]
    if not url.startswith("http"):
        raise ValueError("unexpected decode result")
    return url


def resolve_urls(items):
    """Fill publisher_url for items that don't have one yet; Google link stays in `url`."""
    n_ok = n_fail = 0
    todo = [i for i in items if not i.get("publisher_url")][:MAX_RESOLVE_PER_RUN]
    for i in todo:
        try:
            i["publisher_url"] = resolve_google_url(i["url"])
            i.pop("resolve_error", None)
            n_ok += 1
        except Exception as e:  # noqa: BLE001 - fall back to the Google link
            i["publisher_url"] = None
            i["resolve_error"] = str(e)[:120]
            n_fail += 1
            if "429" in str(e):  # rate-limited: stop now, the rest are retried next run
                break
        time.sleep(1.2)
    return n_ok, n_fail


def build_query(terms):
    parts = [t if '"' in t else (f'"{t}"' if " " in t else t) for t in terms]
    return " OR ".join(parts)


def make_filter(cfg):
    """Returns keep(item) -> bool. Adds the analyst tag to allowed analyst-action items."""
    blocked = {b.lower() for b in cfg.get("blocked_sources", [])}
    bad_urls = [re.compile(x, re.I) for x in cfg.get("blocked_url_patterns", [])]
    always_drop = [re.compile(x, re.I) for x in cfg.get("exclude_title_patterns", [])]
    aa = cfg.get("analyst_actions") or {}
    aa_pats = [re.compile(x, re.I) for x in aa.get("patterns", [])]
    aa_cos = [x.lower() for x in aa.get("companies", [])]
    aa_tag = aa.get("tag", "analyst")
    hi = [re.compile(x, re.I) for x in (cfg.get("digest") or {}).get("exclude_patterns", [])]
    usf = cfg.get("us_focus") or {}
    angle = [re.compile(r"\b" + re.escape(a), re.I) for a in (cfg.get("digest") or {}).get("angle_terms", [])]
    co_terms = [re.compile(r"\b" + re.escape(a), re.I) for a in usf.get("company_terms", [])]
    non_us = [re.compile(x, re.I) for x in usf.get("non_us_markers", [])]
    hi_groups = {g["id"] for g in cfg["groups"] if g.get("exclude_human_interest")}
    drop = aa.get("drop") or {}
    zk_mentions = [x.lower() for x in drop.get("mentions", [])]
    zk_pats = [re.compile(x, re.I) for x in drop.get("patterns", [])]

    def keep(item):
        src, head = item["source"].lower(), item["headline"]
        if any(b in src for b in blocked):
            return False
        if any(p.search(head) for p in always_drop):
            return False
        if item.get("publisher_url") and any(p.search(item["publisher_url"]) for p in bad_urls):
            return False
        if usf:
            if angle and not any(a.search(head) for a in angle):
                return False  # no transplant-industry angle
            names_company = any(c.search(head) for c in co_terms)
            if not names_company and any(m.search(f"{head} {item['source']}") for m in non_us):
                return False  # non-U.S. story without a tracked company
        item["tags"] = [t for t in item["tags"] if t != aa_tag]  # recomputed every run
        if any(p.search(head) for p in hi):  # human-interest: untag from groups that exclude it
            item["tags"] = [t for t in item["tags"] if t not in hi_groups]
        if any(p.search(head) for p in aa_pats):
            if not any(c in head.lower() for c in aa_cos):
                return False
            text = f"{src} {head} {item.get('_snippet', '')}".lower()
            if any(m in text for m in zk_mentions) or any(p.search(head) for p in zk_pats):
                return False
            item["tags"] = sorted(set(item["tags"]) | {aa_tag})
        return bool(item["tags"])
    return keep


def fetch_group(group, days):
    out = []
    for terms in group.get("queries") or [group["terms"]]:
        out.extend(fetch_query(group, terms, days))
    return out


def fetch_query(group, terms, days):
    q = f"({build_query(terms)}) when:{days}d"
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
            "_snippet": re.sub(r"<[^>]+>", " ", desc),  # used for filtering only; not saved
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
    ok, fail = resolve_urls(items)
    print(f"publisher URLs resolved: {ok} ok, {fail} failed (Google link kept)")
    items = [i for i in items if keep(i)]  # re-filter now that publisher URLs are known
    items.sort(key=lambda i: i["date"], reverse=True)
    for i in items:
        i.pop("_snippet", None)

    out = {
        "source": SOURCE,
        "tag": "Live",
        "fetched_at": stamp if fresh_all or not errors else prev.get("fetched_at"),
        "lookback_days": days,
        "groups": [{"id": g["id"], "label": g["label"], "collapsed": bool(g.get("collapsed"))} for g in cfg["groups"]]
                  + ([{"id": cfg["analyst_actions"].get("tag", "analyst"), "label": cfg["analyst_actions"]["label"]}]
                     if cfg.get("analyst_actions") else []),
        "errors": errors,
        "items": items,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"news.json: {len(items)} items kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
