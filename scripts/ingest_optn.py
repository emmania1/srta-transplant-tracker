#!/usr/bin/env python3
"""Ingest OPTN export files dropped into data/raw/optn/ -> data/processed/*.json.

File naming: prefix every dropped file with its download date, e.g.
    2026-10-05_optn_metrics_weekly_transplants.csv
The date is the "as of" used to drop the current, incomplete week.

STATUS: parsers are NOT written yet. Per the build brief, they will be built
against real OPTN exports (column names, organ labels, week/period format),
not guessed. Until a parser recognises a file, every OPTN panel stays in an
explicit "awaiting_data" state and unrecognised files are listed so it is
obvious what still needs handling.

Each parser registers in PARSERS as (name, matches(path, header) -> bool,
parse(path, as_of) -> dict of {processed_file_key: payload}). Output payloads
use the normalized schemas documented in README.md.
"""
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import drop_incomplete  # noqa: E402,F401  (used by parsers)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "optn"
PROC = ROOT / "data" / "processed"
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")

OPTN_METRICS = "OPTN metrics dashboard (optn.transplant.hrsa.gov/data/view-data-reports/optn-metrics)"
OPTN_NATIONAL = "OPTN national data reports (optn.transplant.hrsa.gov/data/view-data-reports/national-data)"

OUTPUTS = {
    "transplants_weekly": {"source": OPTN_METRICS,
                           "title": "Weekly deceased-donor transplants by organ"},
    "donor_mix": {"source": OPTN_NATIONAL,
                  "title": "Deceased donors by type (DBD vs DCD) and DCD share by organ"},
    "distance": {"source": OPTN_NATIONAL,
                 "title": "Deceased-donor transplants by donor-to-center distance band"},
    "location": {"source": OPTN_NATIONAL,
                 "title": "Transplants by transplant-center state / OPTN region"},
}

# Filled in once sample exports are in hand.
PARSERS = []


def raw_files():
    files = []
    for p in sorted(RAW.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        m = DATE_PREFIX.match(p.name)
        files.append((p, date.fromisoformat(m.group(1)) if m else None))
    # newest download first
    files.sort(key=lambda t: (t[1] or date.min, t[0].name), reverse=True)
    return files


def header_of(path):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.readline()
    except OSError:
        return ""


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    files = raw_files()
    results = {}
    unrecognised, undated = [], []

    for path, as_of in files:
        if as_of is None:
            undated.append(path.name)
            continue
        head = header_of(path)
        parser = next((p for p in PARSERS if p[1](path, head)), None)
        if parser is None:
            unrecognised.append(path.name)
            continue
        for key, payload in parser[2](path, as_of).items():
            if key in results:  # newest file for each output wins
                continue
            payload.update({"raw_file": path.name, "data_as_of": as_of.isoformat(),
                            "parser": parser[0]})
            results[key] = payload

    for key, meta in OUTPUTS.items():
        base = {"title": meta["title"], "source": meta["source"], "tag": "Manual",
                "ingested_at": now}
        if key in results:
            base.update(results[key])
            base["status"] = "ok"
        else:
            base.update({"status": "awaiting_data",
                         "note": "No parsed OPTN export yet. Drop a dated file in data/raw/optn/."})
        base["unrecognised_files"] = unrecognised
        base["undated_files"] = undated
        (PROC / f"{key}.json").write_text(json.dumps(base, indent=2) + "\n")
        print(f"{key}.json: {base['status']}")

    if unrecognised:
        print("Unrecognised OPTN files (no parser yet): " + ", ".join(unrecognised))
    if undated:
        print("Files missing YYYY-MM-DD prefix (skipped): " + ", ".join(undated))
    return 0


if __name__ == "__main__":
    sys.exit(main())
