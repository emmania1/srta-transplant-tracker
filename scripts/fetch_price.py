#!/usr/bin/env python3
"""Fetch SRTA daily closes from Yahoo Finance's public chart endpoint (no API key).

Writes data/processed/price.json. On any failure the previous file is kept
untouched (last good value + its date stay on the page) and a fetch_error note
is recorded so the page can say the refresh failed.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed" / "price.json"
TICKER = "SRTA"
HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
SOURCE = "Yahoo Finance chart API (query1.finance.yahoo.com/v8/finance/chart)"


def fetch(host):
    url = f"https://{host}/v8/finance/chart/{TICKER}?range=3mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (srta-tracker)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    res = payload["chart"]["result"][0]
    tz_off = res["meta"].get("gmtoffset", 0)
    closes = res["indicators"]["quote"][0]["close"]
    rows = []
    for ts, c in zip(res["timestamp"], closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts + tz_off, tz=timezone.utc).date().isoformat()
        rows.append({"date": d, "close": round(c, 4)})
    if not rows:
        raise ValueError("no closes returned")
    return rows


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prev = json.loads(OUT.read_text()) if OUT.exists() else None
    err = None
    rows = None
    for host in HOSTS:
        try:
            rows = fetch(host)
            break
        except Exception as e:  # noqa: BLE001 - any failure falls through to next host
            err = f"{host}: {e}"
    if rows is None:
        print(f"Price fetch failed ({err}); keeping last good value.", file=sys.stderr)
        if prev:
            prev["fetch_error"] = {"at": now, "message": err}
            OUT.write_text(json.dumps(prev, indent=2) + "\n")
        else:
            OUT.write_text(json.dumps({
                "ticker": TICKER, "source": SOURCE, "tag": "Live", "status": "awaiting_data",
                "history": [], "fetch_error": {"at": now, "message": err},
            }, indent=2) + "\n")
        return 0

    out = {
        "ticker": TICKER,
        "source": SOURCE,
        "tag": "Live",
        "status": "ok",
        "fetched_at": now,
        "history": rows,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"SRTA: {len(rows)} closes, last {rows[-1]['date']} = {rows[-1]['close']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
