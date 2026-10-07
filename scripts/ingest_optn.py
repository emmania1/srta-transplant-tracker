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
  * Weekly all-organ transplants by OPTN region: ..._deceased_all_regionNN.csv (same format).
  * OPTN national data snapshots in data/raw/optn/national/ (scripts/fetch_optn_national.py),
    parsed by scripts/ingest_national.py into donor_mix / distance / location.
"""
import csv
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import drop_incomplete  # noqa: E402
import ingest_national  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "optn"
PROC = ROOT / "data" / "processed"
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")

OPTN_METRICS = "OPTN metrics dashboard (optn.transplant.hrsa.gov/data/view-data-reports/optn-metrics)"
OPTN_METRICS_LIVE = ("OPTN metrics dashboard, Transplant Details > Download Data "
                     "(insights.unos.org/OPTN-metrics), fetched by scripts/fetch_optn.py")
OPTN_NATIONAL = ("OPTN national data reports (hrsa.unos.org/data/view-data-reports/national-data), "
                 "fetched monthly by scripts/fetch_optn_national.py")

OUTPUTS = {
    "transplants_weekly": {"source": OPTN_METRICS,
                           "title": "Weekly deceased-donor transplants by organ"},
    "donors_weekly": {"source": OPTN_METRICS,
                      "title": "Weekly deceased donors recovered + YTD all-organs discard rate"},
    "donor_mix": {"source": OPTN_NATIONAL,
                  "title": "Deceased donors by type (DBD vs DCD) and DCD share by organ"},
    "distance": {"source": OPTN_NATIONAL,
                 "title": "Deceased-donor transplants by donor-to-center distance band"},
    "location": {"source": OPTN_NATIONAL,
                 "title": "Deceased-donor transplants by transplant-center state (monthly snapshots)"},
    "regions_weekly": {"source": OPTN_METRICS,
                       "title": "Weekly deceased-donor transplants (all organs) by OPTN region"},
}

WEEKLY_FILE = re.compile(r"_optn_metrics_tx_weekly_deceased_(heart|liver|lung|kidney|all)\.csv$")
WEEKLY_HEADER = ["yr", "week", "full_wk", "n", "cum_n"]
DON_WEEKLY_FILE = re.compile(r"_optn_metrics_don_weekly_deceased\.csv$")
DON_TABLE_FILE = re.compile(r"_optn_metrics_don_table_deceased\.csv$")
DON_META_FILE = re.compile(r"_optn_metrics_don_table_meta\.json$")
DON_TABLE_HEADER = ["yr", "total", "pct_chg", "disc", "util"]
REGION_FILE = re.compile(r"_optn_metrics_tx_weekly_deceased_all_region(\d{2})\.csv$")
REGIONS_CONFIG = ROOT / "config" / "optn_regions.json"
LIVE_OUTPUTS = {"transplants_weekly", "donors_weekly", "regions_weekly", "donor_mix", "distance", "location"}


def parse_don_table(path, meta_path):
    """Don_Table.csv: deceased donors recovered year-to-date (same calendar span each year)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        if next(reader) != DON_TABLE_HEADER:
            raise ValueError(f"{path.name}: unexpected header")
        rows = [{"yr": int(yr), "ytd_deceased_donors": int(total),
                 "ytd_pct_chg": None if pct == "NA" else round(100 * float(pct), 2),
                 "discard_rate_pct": round(100 * float(disc), 2),
                 "utilization_rate_pct": round(100 * float(util), 2)}
                for yr, total, pct, disc, util in reader]
    rows.sort(key=lambda r: r["yr"])
    through = json.loads(meta_path.read_text())["ytd_through"] if meta_path else None
    return rows, through


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
    don = {}     # weekly / table / meta -> (path, as_of)
    regions = {}  # "1".."11" -> (path, as_of)
    for path, as_of in files:
        if as_of is None:
            undated.append(path.name)
            continue
        if DON_WEEKLY_FILE.search(path.name):
            don.setdefault("weekly", (path, as_of))
            continue
        if DON_TABLE_FILE.search(path.name):
            don.setdefault("table", (path, as_of))
            continue
        if DON_META_FILE.search(path.name):
            don.setdefault("meta", (path, as_of))
            continue
        rm = REGION_FILE.search(path.name)
        if rm:
            regions.setdefault(str(int(rm.group(1))), (path, as_of))
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
            "note": ("'all' = OPTN's All Organs deceased-donor total (includes pancreas, intestine, etc.). "
                     "The dashboard's 'Kidney' includes kidney-pancreas transplants: 2025 = 21,856 vs 21,052 "
                     "kidney-alone + 804 kidney-pancreas in OPTN national data."),
            "organ_definitions": {"kidney": "Includes kidney-pancreas transplants (OPTN metrics dashboard definition)"},
        }

    if "weekly" in don:
        path, as_of = don["weekly"]
        rows, dropped = parse_weekly(path, as_of)
        payload = {"donors": rows, "excluded_incomplete_weeks": [f"{r['yr']}-W{r['week']:02d}" for r in dropped],
                   "raw_file": path.name, "data_as_of": as_of.isoformat(), "parser": "optn_metrics_don_weekly",
                   "donor_type": "Deceased Donors", "region": "National", "ytd_table": None}
        if "table" in don:
            tpath, tas_of = don["table"]
            meta = don.get("meta")
            same_pull = meta and meta[1] == tas_of
            table, through = parse_don_table(tpath, meta[0] if same_pull else None)
            payload.update({"ytd_table": table, "ytd_through": through,
                            "ytd_table_file": tpath.name, "ytd_table_as_of": tas_of.isoformat(),
                            "discard_rate_definition": "OPTN metrics dashboard 'All Organs Discard Rate' for deceased donors recovered year to date"})
        results["donors_weekly"] = payload

    if regions:
        cfg = json.loads(REGIONS_CONFIG.read_text())
        series, excluded = {}, {}
        for r, (path, as_of) in sorted(regions.items(), key=lambda kv: int(kv[0])):
            rows, dropped = parse_weekly(path, as_of)
            series[r] = rows
            excluded[r] = [f"{x['yr']}-W{x['week']:02d}" for x in dropped]
        results["regions_weekly"] = {
            "regions": series, "excluded_incomplete_weeks": excluded,
            "region_states": cfg["regions"], "region_states_source": cfg["_source"],
            "raw_file": ", ".join(p.name for p, _ in regions.values()),
            "data_as_of": min(a for _, a in regions.values()).isoformat(),
            "parser": "optn_metrics_tx_weekly", "donor_type": "Deceased Donors", "organ": "All Organs",
        }

    results.update(ingest_national.build_all(RAW / "national"))

    for key, meta in OUTPUTS.items():
        base = {"title": meta["title"], "source": meta["source"], "tag": "Manual",
                "ingested_at": now}
        if key in results:
            if key in LIVE_OUTPUTS:
                base["tag"] = "Live"
                if base["source"] == OPTN_METRICS:
                    base["source"] = OPTN_METRICS_LIVE
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
