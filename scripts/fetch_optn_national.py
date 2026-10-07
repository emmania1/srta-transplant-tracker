#!/usr/bin/env python3
"""Fetch OPTN national data reports (annual / year-to-date) by plain HTTP.

Source: https://hrsa.unos.org/data/view-data-reports/national-data (embedded at
hrsa.gov/optn -> Data & Calculators -> Data Reports -> National data). The page is
a form backed by an OLAP cube: GET it for an anti-forgery cookie + token, then
POST report parameters and read the HTML table that comes back (the site's
"Export CSV" is client-side only). No login, no browser.

OPTN refreshes these monthly and they have no month dimension: columns are
"To Date", the current year through the last full month, and prior full years.
This script runs weekly but only writes a new snapshot when OPTN's reporting
period end changes, so data/raw/optn/national/ accumulates one snapshot per
month. Successive snapshots are what make same-period YoY possible later.

Output per query:
  data/raw/optn/national/<download date>_optn_national_<query>_thru-<period end>.csv
  columns: group, row, column, value   (group = Donor Type, row = second field)
plus <download date>_optn_national_meta_thru-<period end>.json
"""
import csv
import html as H
import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "optn" / "national"
URL = "https://hrsa.unos.org/data/view-data-reports/national-data"
UA = "Mozilla/5.0 (srta-transplant-tracker; public OPTN national data)"

ROW1 = "[Donor Type].members;Donor Type;0;Donor Type"
DCD = "[Donation After Circulatory Death].members;Donation After Circulatory Death (DCD);5;Donation After Circulatory Death"
ZONE = "[Zone].members;Distance to Transplant Center;11;Zone"
STATE = "[State].members;Center State;53;State"
ORGANS = {"heart": "Heart", "liver": "Liver", "lung": "Lung", "kidney": "Kidney"}


def organ_slice(label):
    return f"{label};{label};8;Organ;Organ" if label else ""


QUERIES = {"donors_dcd": ("1;Donor", 1, DCD, "")}
for key, label in ORGANS.items():
    QUERIES[f"tx_dcd_{key}"] = ("2;Transplant", 14, DCD, organ_slice(label))
    QUERIES[f"tx_distance_{key}"] = ("2;Transplant", 14, ZONE, organ_slice(label))
QUERIES["tx_state_all"] = ("2;Transplant", 14, STATE, "")


class Session:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.addheaders = [("User-Agent", UA)]
        page = self.op.open(URL, timeout=60).read().decode()
        m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page)
        if not m:
            raise RuntimeError("anti-forgery token not found on national-data page")
        self.token = m.group(1)

    def report(self, category, report_id, row2, slice0):
        fields = {
            "Category": category, "CategoryId": category.split(";")[0], "CubeName": category.split(";")[1],
            "ReportId": report_id, "row1": ROW1, "row2": row2, "slice0": slice0,
            "MaximumSlice": 1, "ReportType": "Data", "NumberStyle": "Values",
            "FilterType": "National", "strFilterType": "National",
            "__RequestVerificationToken": self.token,
        }
        body = urllib.parse.urlencode(fields).encode()
        return self.op.open(URL, data=body, timeout=180).read().decode()


def cells(tr):
    return [H.unescape(re.sub(r"<[^>]+>", "", c)).replace("\xa0", " ").strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]


def parse(page):
    """Return (meta, rows) from a report page."""
    period = re.search(r":\s*January 1, 1988 - ([A-Z][a-z]+ \d{1,2}, \d{4})", page)
    as_of = re.search(r"based on OPTN data as of ([A-Z][a-z]+ \d{1,2}, \d{4})", page)
    if not period or not as_of:
        raise RuntimeError("could not find reporting period / data-as-of text")
    trs = [cells(tr) for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S)]
    header_i = next(i for i, c in enumerate(trs) if len(c) > 3 and "To Date" in c)
    header = trs[header_i]
    years = header[header.index("To Date"):]
    rows, group = [], None
    for c in trs[header_i + 1:]:
        if len(c) != len(header) or "To Date" in c:  # header repeats every on-screen page
            continue
        group = c[0] or group
        label = c[1]
        for col, val in zip(years, c[header.index("To Date"):]):
            rows.append({"group": group, "row": label, "column": col,
                         "value": int(val.replace(",", "")) if val else 0})
    if not rows:
        raise RuntimeError("no data rows parsed")
    meta = {
        "period_end": datetime.strptime(period.group(1), "%B %d, %Y").date().isoformat(),
        "data_as_of": datetime.strptime(as_of.group(1), "%B %d, %Y").date().isoformat(),
    }
    return meta, rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    s = Session()
    results, metas = {}, set()
    for key, (cat, rid, row2, slice0) in QUERIES.items():
        meta, rows = parse(s.report(cat, rid, row2, slice0))
        metas.add((meta["period_end"], meta["data_as_of"]))
        results[key] = (meta, rows)
        print(f"{key}: {len(rows)} cells, period through {meta['period_end']}")
    if len({m[0] for m in metas}) != 1:
        raise RuntimeError(f"queries returned different reporting periods: {metas}")
    period_end, data_as_of = sorted(metas)[-1]

    if list(OUT.glob(f"*_optn_national_meta_thru-{period_end}.json")):
        print(f"Snapshot through {period_end} already saved; OPTN has not refreshed. Nothing written.")
        return 0
    for key, (_, rows) in results.items():
        path = OUT / f"{today}_optn_national_{key}_thru-{period_end}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["group", "row", "column", "value"])
            w.writeheader()
            w.writerows(rows)
    (OUT / f"{today}_optn_national_meta_thru-{period_end}.json").write_text(json.dumps({
        "period_end": period_end, "data_as_of": data_as_of, "downloaded": today,
        "source": URL, "queries": {k: {"category": v[0], "report_id": v[1], "row2": v[2], "slice0": v[3]}
                                   for k, v in QUERIES.items()},
    }, indent=2) + "\n")
    print(f"New snapshot through {period_end} (OPTN data as of {data_as_of}) written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
