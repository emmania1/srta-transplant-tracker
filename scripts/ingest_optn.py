#!/usr/bin/env python3
"""Ingest OPTN export files dropped into data/raw/optn/ -> data/processed/*.json.

File naming: prefix every dropped file with its download date, e.g.
    2026-10-05_optn_metrics_weekly_transplants.csv
The date is the "as of" used to drop the current, incomplete week.

Parsers:
  * OPTN metrics weekly transplants (written by scripts/fetch_optn.py):
      YYYY-MM-DD_optn_metrics_tx_weekly_deceased_<organ>.csv
      columns "yr","week","full_wk","n","cum_n"; full_wk = "(Partial Week)" marks
      the current unfinished week. OPTN weeks are calendar-year weeks 1-52:
      week N starts Jan 1 + 7*(N-1); week 52 runs to Dec 31 (8-9 days).
  * Donor mix / distance / location: not written yet. They will be built against
    real OPTN national-data exports, not guessed. Until then those panels stay
    "awaiting_data" and unrecognised files are listed.
"""
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import drop_incomplete  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "optn"
PROC = ROOT / "data" / "processed"
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")

OPTN_METRICS = "OPTN metrics dashboard (optn.transplant.hrsa.gov/data/view-data-reports/optn-metrics)"
OPTN_METRICS_LIVE = ("OPTN metrics dashboard, Transplant Details > Download Data "
                     "(insights.unos.org/OPTN-metrics), fetched by scripts/fetch_optn.py")
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

WEEKLY_FILE = re.compile(r"_optn_metrics_tx_weekly_deceased_(heart|liver|lung|kidney|all)\.csv$")
WEEKLY_HEADER = ["yr", "week", "full_wk", "n", "cum_n"]


def optn_week_dates(yr, week):
    start = date(yr, 1, 1) + timedelta(days=7 * (week - 1))
    end = date(yr, 12, 31) if week == 52 else start + timedelta(days=6)
    return start, end


def parse_weekly(path, as_of):
    """Returns (rows, dropped) for one organ's TX_Weekly.csv."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        if next(reader) != WEEKLY_HEADER:
            raise ValueError(f"{path.name}: unexpected header")
        rows, flagged = [], []
        for yr, week, full_wk, n, _cum in reader:
            yr, week = int(yr), int(week)
            start, end = optn_week_dates(yr, week)
            row = {"yr": yr, "week": week, "week_start": start.isoformat(),
                   "week_end": end.isoformat(), "count": int(n)}
            (flagged if full_wk.strip() else rows).append(row)
    # belt and braces: also drop anything not finished before the pull date
    rows, late = drop_incomplete(rows, as_of)
    return rows, flagged + late


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

    weekly = {}  # organ -> (path, as_of); newest download wins
    for path, as_of in files:
        if as_of is None:
            undated.append(path.name)
            continue
        m = WEEKLY_FILE.search(path.name)
        if m and header_of(path).replace('"', "").strip().split(",") == WEEKLY_HEADER:
            weekly.setdefault(m.group(1), (path, as_of))
        else:
            unrecognised.append(path.name)

    if weekly:
        organs, excluded, files_used = {}, {}, []
        for organ, (path, as_of) in sorted(weekly.items()):
            rows, dropped = parse_weekly(path, as_of)
            organs[organ] = rows
            excluded[organ] = [f"{r['yr']}-W{r['week']:02d}" for r in dropped]
            files_used.append(path.name)
        as_of = min(a for _, a in weekly.values())
        results["transplants_weekly"] = {
            "organs": organs, "excluded_incomplete_weeks": excluded,
            "raw_file": ", ".join(files_used), "data_as_of": as_of.isoformat(),
            "parser": "optn_metrics_tx_weekly",
            "week_definition": "OPTN calendar-year week: week N starts Jan 1 + 7*(N-1); week 52 runs to Dec 31",
            "donor_type": "Deceased Donors", "region": "National",
            "note": "'all' = OPTN's All Organs deceased-donor total (includes pancreas, intestine, etc.)",
        }

    for key, meta in OUTPUTS.items():
        base = {"title": meta["title"], "source": meta["source"], "tag": "Manual",
                "ingested_at": now}
        if key in results:
            if key == "transplants_weekly":
                base["source"] = OPTN_METRICS_LIVE
                base["tag"] = "Live"
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
