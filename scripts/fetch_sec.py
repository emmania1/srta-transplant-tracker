#!/usr/bin/env python3
"""SRTA filings from SEC EDGAR (data.sec.gov submissions API, no key).

SEC requires a User-Agent that identifies the requester with a contact email
(https://www.sec.gov/os/accessing-edgar-data). It is read from the SEC_USER_AGENT
environment variable (a GitHub Actions secret), e.g. "srta-transplant-tracker you@example.com",
so no email is committed to this public repo.

Keeps 180 days of: 8-K, 10-Q, 10-K, Form 4 (+/A), Schedule 13D/13G (+/A, both the
current "SCHEDULE 13D" and legacy "SC 13D" names), DEF 14A. Form 4s are parsed
for open-market sales (transaction code S) so the digest can flag them.

Writes data/processed/sec_filings.json; keeps the previous file on failure.
"""
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed" / "sec_filings.json"
CIK = "1779128"  # Strata Critical Medical, Inc. (SEC company_tickers.json)
DAYS = 180
FORMS = re.compile(r"^(8-K|10-Q|10-K|4|DEF 14A|SC 13[DG]|SCHEDULE 13[DG])(/A)?$")
SOURCE = f"SEC EDGAR submissions API (data.sec.gov/submissions/CIK{int(CIK):010d}.json)"


def get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def form4_summary(xml_bytes):
    """Owner, role and non-derivative transactions from a Form 4 XML."""
    root = ET.fromstring(xml_bytes)
    owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName") or ""
    rel = root.find(".//reportingOwner/reportingOwnerRelationship")
    roles = []
    if rel is not None:
        if (rel.findtext("isDirector") or "").strip() in ("1", "true"):
            roles.append("Director")
        if (rel.findtext("isOfficer") or "").strip() in ("1", "true"):
            roles.append(rel.findtext("officerTitle") or "Officer")
        if (rel.findtext("isTenPercentOwner") or "").strip() in ("1", "true"):
            roles.append("10% owner")
    txns = []
    for t in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        def v(path):
            return (t.findtext(path) or "").strip()
        shares = v("transactionAmounts/transactionShares/value")
        price = v("transactionAmounts/transactionPricePerShare/value")
        txns.append({"date": v("transactionDate/value"), "code": v("transactionCoding/transactionCode"),
                     "shares": float(shares) if shares else None, "price": float(price) if price else None,
                     "acquired_disposed": v("transactionAmounts/transactionAcquiredDisposedCode/value")})
    sales = [x for x in txns if x["code"] == "S"]
    return {"owner": owner, "roles": roles, "transactions": txns,
            "open_market_sale": bool(sales),
            "shares_sold": sum(x["shares"] or 0 for x in sales) or None}


def main():
    now = datetime.now(timezone.utc)
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    prev = json.loads(OUT.read_text()) if OUT.exists() else None
    if "@" not in ua:
        msg = "SEC_USER_AGENT is not set (SEC requires a contact email in the User-Agent)."
        print(msg, file=sys.stderr)
        payload = prev or {"status": "not_configured", "tag": "Live", "source": SOURCE, "filings": []}
        payload["config_note"] = msg
        OUT.write_text(json.dumps(payload, indent=2) + "\n")
        return 0  # a missing secret is a setup step, not a broken scrape
    known = {f["accession"]: f for f in (prev or {}).get("filings", [])}
    try:
        sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{int(CIK):010d}.json", ua))
        r = sub["filings"]["recent"]
        cutoff = (now.date() - timedelta(days=DAYS)).isoformat()
        filings = []
        for i, form in enumerate(r["form"]):
            if r["filingDate"][i] < cutoff or not FORMS.match(form):
                continue
            acc = r["accessionNumber"][i]
            folder = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc.replace('-', '')}"
            doc = r["primaryDocument"][i]
            f = {"accession": acc, "form": form, "filed": r["filingDate"][i],
                 "report_date": r["reportDate"][i] or None,
                 "description": r["primaryDocDescription"][i] or form,
                 "items": r.get("items", [""] * len(r["form"]))[i] or None,
                 "url": f"{folder}/{doc}", "index_url": f"{folder}/{acc}-index.htm"}
            if form.startswith("4"):
                if acc in known and "form4" in known[acc]:
                    f["form4"] = known[acc]["form4"]
                else:
                    raw = doc.split("/")[-1]  # strip the xsl rendering prefix to get the XML
                    try:
                        f["form4"] = form4_summary(get(f"{folder}/{raw}", ua))
                    except Exception as e:  # noqa: BLE001
                        f["form4_error"] = str(e)[:120]
                    time.sleep(0.15)  # SEC fair-access: stay well under 10 requests/second
            filings.append(f)
    except Exception as e:  # noqa: BLE001
        print(f"SEC fetch failed: {e}", file=sys.stderr)
        payload = prev or {"status": "awaiting_data", "tag": "Live", "source": SOURCE, "filings": []}
        payload["fetch_error"] = {"at": now.isoformat(timespec="seconds"), "message": str(e)[:200]}
        OUT.write_text(json.dumps(payload, indent=2) + "\n")
        return 1

    out = {"title": "SRTA SEC filings (last 180 days)", "company": sub.get("name"), "cik": CIK,
           "source": SOURCE, "tag": "Live", "status": "ok",
           "fetched_at": now.isoformat(timespec="seconds"), "days": DAYS, "filings": filings}
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    sales = [f for f in filings if (f.get("form4") or {}).get("open_market_sale")]
    print(f"SEC: {len(filings)} filings in {DAYS} days; {len(sales)} Form 4s with open-market sales")
    return 0


if __name__ == "__main__":
    sys.exit(main())
