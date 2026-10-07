#!/usr/bin/env python3
"""Fetch weekly deceased-donor transplant counts from the public OPTN metrics dashboard.

The dashboard (https://insights.unos.org/OPTN-metrics/, embedded at
hrsa.gov/optn -> Data & Calculators -> Dashboards & Metrics) is an R Shiny app
on Posit Connect. It has no static data URL: each visitor gets a server-side
session over a websocket, and the "Download Data" button on the Transplant
Details tab serves a zip from a session-scoped URL
(.../session/<id>/download/tx_download). No login or cookie is needed, but the
session only exists once the app's JavaScript has run, so this script drives a
headless Chromium (Playwright) to open the app, set the Organ + Donor inputs,
and pull each zip from inside the page.

Writes, per run (dated with the download date):
    data/raw/optn/YYYY-MM-DD_optn_metrics_tx_weekly_deceased_<organ>.csv   (Transplant Details)
    data/raw/optn/YYYY-MM-DD_optn_metrics_don_weekly_deceased.csv          (Donor Details: weekly donors)
    data/raw/optn/YYYY-MM-DD_optn_metrics_don_table_deceased.csv           (Donor Details: YTD discard/utilization)
    data/raw/optn/YYYY-MM-DD_optn_metrics_don_table_meta.json              ("through <date>" for that table)
which scripts/ingest_optn.py then parses. Exits non-zero if any organ fails,
leaving earlier files in place, so the page keeps the last good data.
"""
import base64
import csv
import io
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "optn"
APP = "https://insights.unos.org/OPTN-metrics/"
# dashboard option label -> our organ key ("all" = OPTN's All Organs total)
ORGANS = {"Heart": "heart", "Liver": "liver", "Lung": "lung", "Kidney": "kidney", "All Organs": "all"}
DONOR = "Deceased Donors"
EXPECTED_HEADER = ["yr", "week", "full_wk", "n", "cum_n"]

DON_HEADER = ["yr", "total", "pct_chg", "disc", "util"]

# Generic: set selectize inputs, then pull the zip behind download link `link`
# once its Content-Disposition names the file we asked for.
FETCH_JS = """async ([inputs, link, want]) => {
  for (const [id, v] of Object.entries(inputs)) document.getElementById(id).selectize.setValue(v);
  const a = document.getElementById(link);
  for (let i = 0; i < 60; i++) {           // wait for Shiny to re-render (<= 60s)
    await new Promise(r => setTimeout(r, 1000));
    if (!a.href.includes('/download/')) continue;
    const r = await fetch(a.href, {cache: 'no-store'});
    const disp = r.headers.get('content-disposition') || '';
    if (r.ok && disp.includes(want)) {
      const buf = new Uint8Array(await r.arrayBuffer());
      let s = ''; for (const b of buf) s += String.fromCharCode(b);
      return {disp, b64: btoa(s)};
    }
  }
  return {error: `timed out waiting for ${want}`};
}"""


def main():
    today = date.today().isoformat()
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent="Mozilla/5.0 (srta-transplant-tracker; public OPTN metrics)")
        page.goto(APP, wait_until="networkidle", timeout=120_000)
        page.wait_for_function("window.Shiny && Shiny.shinyapp && Shiny.shinyapp.isConnected()", timeout=60_000)
        # the download link only gets its session URL once the Transplant Details tab renders
        page.get_by_text("Transplant Details", exact=True).click()
        page.wait_for_function("document.getElementById('tx_download').href.includes('/download/')", timeout=60_000)

        for label, key in ORGANS.items():
            res = page.evaluate(FETCH_JS, [{"don_ty": DONOR, "tx_wl_organ": label}, "tx_download",
                                           f"{DONOR}_{label}_TX_dat.zip"])
            if "error" in res:
                failures.append(f"{label}: {res['error']}")
                continue
            z = zipfile.ZipFile(io.BytesIO(base64.b64decode(res["b64"])))
            text = z.read("TX_Weekly.csv").decode("utf-8-sig")
            header = next(csv.reader(io.StringIO(text)))
            if header != EXPECTED_HEADER:
                failures.append(f"{label}: unexpected TX_Weekly.csv header {header}")
                continue
            out = RAW / f"{today}_optn_metrics_tx_weekly_deceased_{key}.csv"
            out.write_text(text)
            print(f"{label}: {len(text.splitlines()) - 1} weekly rows -> {out.name}")

        # Deceased donors recovered (weekly) + YTD discard/utilization table
        page.get_by_text("Donor Details", exact=True).click()
        page.wait_for_function("document.getElementById('don_download').href.includes('/download/')", timeout=60_000)
        res = page.evaluate(FETCH_JS, [{"don_ty": DONOR, "don_organ": "All Organs"}, "don_download",
                                       f"{DONOR}_All Organs_Don_dat.zip"])
        if "error" in res:
            failures.append(f"Donors: {res['error']}")
        else:
            z = zipfile.ZipFile(io.BytesIO(base64.b64decode(res["b64"])))
            weekly = z.read("Don_Weekly.csv").decode("utf-8-sig")
            table = z.read("Don_Table.csv").decode("utf-8-sig")
            # Don_Table is year-to-date "through <Month D>"; that date is only in the page heading
            m = re.search(r"Deceased Donors Recovered through (\w+ \d{1,2})", page.inner_text(".content-wrapper"))
            if next(csv.reader(io.StringIO(weekly))) != EXPECTED_HEADER:
                failures.append("Donors: unexpected Don_Weekly.csv header")
            elif next(csv.reader(io.StringIO(table))) != DON_HEADER:
                failures.append("Donors: unexpected Don_Table.csv header")
            elif not m:
                failures.append("Donors: could not read the Don_Table 'through' date")
            else:
                (RAW / f"{today}_optn_metrics_don_weekly_deceased.csv").write_text(weekly)
                (RAW / f"{today}_optn_metrics_don_table_deceased.csv").write_text(table)
                (RAW / f"{today}_optn_metrics_don_table_meta.json").write_text(
                    json.dumps({"ytd_through": m.group(1), "heading": m.group(0)}) + "\n")
                print(f"Donors: {len(weekly.splitlines()) - 1} weekly rows; table YTD through {m.group(1)}")
        browser.close()

    if failures:
        print("OPTN fetch failures:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
