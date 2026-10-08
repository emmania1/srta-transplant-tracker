#!/usr/bin/env python3
"""Fetch daily closes for SRTA, TMDX and JOBY from Yahoo Finance's public chart endpoint (no API key).

Writes data/processed/price.json as {"tickers": {SYM: {"history": [...], ...}}}. If a ticker's
fetch fails, its previous history is kept (last good value + date stay on the page) and a
fetch_error is recorded for that ticker.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed" / "price.json"
TICKERS = ["SRTA", "TMDX", "JOBY"]
HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
SOURCE = "Yahoo Finance chart API (query1.finance.yahoo.com/v8/finance/chart)"


def fetch(host, ticker):
    url = f"https://{host}/v8/finance/chart/{ticker}?range=6mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (srta-tracker)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    res = payload["chart"]["result"][0]
    tz_off = res["meta"].get("gmtoffset", 0)
    rows = []
    for ts, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts + tz_off, tz=timezone.utc).date().isoformat()
        rows.append({"date": d, "close": round(c, 4)})
    if not rows:
        raise ValueError("no closes returned")
    return rows


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    prev_t = prev.get("tickers") or ({"SRTA": prev} if prev.get("history") else {})
    out = {"source": SOURCE, "tag": "Live", "fetched_at": now, "tickers": {}}
    failed = 0
    for t in TICKERS:
        rows, err = None, None
        for host in HOSTS:
            try:
                rows = fetch(host, t)
                break
            except Exception as e:  # noqa: BLE001
                err = f"{host}: {e}"
        if rows:
            out["tickers"][t] = {"status": "ok", "fetched_at": now, "history": rows}
            print(f"{t}: {len(rows)} closes, last {rows[-1]['date']} = {rows[-1]['close']}")
        else:
            failed += 1
            keep = dict(prev_t.get(t) or {"status": "awaiting_data", "history": []})
            keep.pop("source", None)
            keep["fetch_error"] = {"at": now, "message": err}
            out["tickers"][t] = keep
            print(f"{t}: fetch failed ({err}); keeping last good value", file=sys.stderr)
    out["status"] = "ok" if any(v.get("history") for v in out["tickers"].values()) else "awaiting_data"
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
