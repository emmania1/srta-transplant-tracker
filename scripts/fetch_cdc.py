#!/usr/bin/env python3
"""CDC/NCHS VSRR provisional drug overdose deaths (dataset xkb8-kh2a, Socrata API, no key).

U.S. 12-month-ending counts by month, reported and predicted (CDC's adjustment for
reporting delay), with YoY vs the same 12-month-ending month a year earlier.
Context: overdose deaths are a leading indicator for brain-death (DBD) donor supply.

Writes data/processed/cdc_overdose.json. On failure the previous file is kept and
a fetch_error is recorded.
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed" / "cdc_overdose.json"
DATASET = "xkb8-kh2a"
API = f"https://data.cdc.gov/resource/{DATASET}.json"
META = f"https://data.cdc.gov/api/views/{DATASET}.json"
INDICATOR = "Number of Drug Overdose Deaths"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "srta-transplant-tracker"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def yoy(cur, prior):
    return round(100 * (cur / prior - 1), 1) if cur is not None and prior else None


def num(v):
    return int(float(v)) if v not in (None, "") else None


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prev = json.loads(OUT.read_text()) if OUT.exists() else None
    try:
        q = urllib.parse.urlencode({"state": "US", "indicator": INDICATOR, "period": "12 month-ending",
                                    "$limit": 5000})
        rows = get(f"{API}?{q}")
        meta = get(META)
    except Exception as e:  # noqa: BLE001
        print(f"CDC fetch failed: {e}", file=sys.stderr)
        payload = prev or {"status": "awaiting_data", "tag": "Live", "series": []}
        payload["fetch_error"] = {"at": now, "message": str(e)[:200]}
        OUT.write_text(json.dumps(payload, indent=2) + "\n")
        return 1

    by_key = {}
    for r in rows:
        key = (int(r["year"]), MONTHS.index(r["month"]) + 1)
        by_key[key] = {"year": key[0], "month": key[1], "period_end": f"{key[0]}-{key[1]:02d}",
                       "reported": num(r.get("data_value")), "predicted": num(r.get("predicted_value")),
                       "footnote": r.get("footnote")}
    series = [by_key[k] for k in sorted(by_key)]
    for s in series:
        p = by_key.get((s["year"] - 1, s["month"]))
        s["reported_yoy_pct"] = yoy(s["reported"], p and p["reported"])
        s["predicted_yoy_pct"] = yoy(s["predicted"], p and p["predicted"])

    out = {
        "title": "U.S. drug overdose deaths, 12-month ending (provisional)",
        "source": f"CDC/NCHS VSRR Provisional Drug Overdose Death Counts (data.cdc.gov dataset {DATASET})",
        "tag": "Live", "status": "ok" if series else "awaiting_data",
        "fetched_at": now,
        "dataset_updated": datetime.fromtimestamp(meta["rowsUpdatedAt"], timezone.utc).date().isoformat(),
        "indicator": INDICATOR,
        "note": ("Leading indicator for brain-death (DBD) donor supply. 'Predicted' is CDC's estimate adjusted "
                 "for reporting delays; 'reported' is counts received so far. Recent months are provisional."),
        "series": series,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    last = series[-1]
    print(f"CDC overdose: {len(series)} months, latest 12 mo ending {last['period_end']}: "
          f"predicted {last['predicted']} ({last['predicted_yoy_pct']}% YoY)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
