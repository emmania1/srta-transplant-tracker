#!/usr/bin/env python3
"""Fetcher health check -> data/processed/health.json.

Issues (banner on the page + 'Data issue:' line in the digest):
  * any fetch step that failed in this workflow run (STEP_OUTCOMES env, JSON {step: outcome})
  * OPTN weekly data whose latest complete week ended more than N days ago
  * OPTN monthly national data, CDC data or prices older than their thresholds
  * per-source fetch_error / errors recorded in the processed files
Notices (shown small, no banner): setup steps such as a missing SEC_USER_AGENT secret.
Thresholds: config/health.json.
"""
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
CFG = json.loads((ROOT / "config" / "health.json").read_text())


def load(name):
    p = PROC / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def age(d, today):
    return (today - date.fromisoformat(d[:10])).days if d else None


RAW = ROOT / "data" / "raw" / "optn"


def step_issues(steps):
    """Plain-English issues from this run's step outcomes (STEP_OUTCOMES)."""
    out = []
    pw_failed = steps.get("Playwright install") == "failure"
    for step, outcome in steps.items():
        if step == "Playwright install" and outcome == "failure":
            out.append("Playwright (the headless browser the OPTN weekly fetch needs) failed to install, so the "
                       "OPTN weekly fetch was skipped; showing the last good OPTN weekly data.")
        elif step == "OPTN weekly" and outcome == "skipped" and pw_failed:
            continue  # already explained by the Playwright line
        elif outcome == "failure":
            out.append(f"{step} step failed in the latest run; showing the last good data.")
    return out


def identical_latest_downloads(pattern="*_optn_metrics_tx_weekly_deceased_all.csv"):
    """(older, newer) dates if the two newest OPTN weekly downloads are byte-identical, else None.
    Identical files mean OPTN's dashboard served the same data twice (the delay is on OPTN's side)."""
    files = sorted(RAW.glob(pattern))
    if len(files) < 2:
        return None
    a, b = files[-2], files[-1]
    return (a.name[:10], b.name[:10]) if a.read_bytes() == b.read_bytes() else None


def main():
    today = date.today()
    issues, notices = [], []
    steps = json.loads(os.environ.get("STEP_OUTCOMES") or "{}")
    issues += step_issues(steps)
    same = identical_latest_downloads()

    max_w = CFG["weekly_optn_max_age_days"]
    for name, key, label in [("transplants_weekly", "organs", "transplants"), ("donors_weekly", None, "donors"),
                             ("waitlist_weekly", "organs", "waitlist additions"), ("regions_weekly", "regions", "regions")]:
        d = load(name)
        if not d or d.get("status") != "ok":
            issues.append(f"OPTN weekly {label}: no data.")
            continue
        series = d["donors"] if key is None else [r for rows in d[key].values() for r in rows]
        last = max((r["week_end"] for r in series), default=None)
        a = age(last, today)
        limit = CFG.get("weekly_optn_donors_max_age_days", max_w) if label == "donors" else max_w
        if a is None or a > limit:
            msg = f"OPTN weekly {label}: latest complete week ended {last} ({a} days ago, limit {limit})."
            if same and label == "transplants":
                msg += (f" OPTN's dashboard returned identical data on {same[0]} and {same[1]}, "
                        "so OPTN has not published newer weeks.")
            issues.append(msg)

    for name, label in [("donor_mix", "monthly donor mix / distance / state"), ("centers", "monthly centers")]:
        d = load(name)
        a = age((d or {}).get("period_end"), today)
        if a is None or a > CFG["national_optn_max_age_days"]:
            issues.append(f"OPTN {label}: data through {(d or {}).get('period_end')} is {a} days old.")

    cdc = load("cdc_overdose") or {}
    if cdc.get("fetch_error"):
        issues.append(f"CDC overdose fetch failed: {cdc['fetch_error']['message'][:80]}")
    a = age(cdc.get("dataset_updated"), today)
    if a is None or a > CFG["cdc_max_dataset_age_days"]:
        issues.append(f"CDC overdose dataset last updated {cdc.get('dataset_updated')} ({a} days ago).")

    price = load("price") or {}
    for t, v in (price.get("tickers") or {}).items():
        if v.get("fetch_error"):
            issues.append(f"{t} price fetch failed; showing close from {(v.get('history') or [{}])[-1].get('date')}.")
        a = age((v.get("history") or [{}])[-1].get("date"), today)
        if a is None or a > CFG["price_max_age_days"]:
            issues.append(f"{t} price: last close is {a} days old.")

    news = load("news") or {}
    if news.get("errors"):
        issues.append(f"News: {len(news['errors'])} keyword query(ies) failed ({', '.join(e.split(':')[0] for e in news['errors'])}).")

    features = json.loads((ROOT / "config" / "features.json").read_text())
    sec = (load("sec_filings") or {}) if features.get("sec_filings") else {}
    if sec.get("fetch_error"):
        issues.append(f"SEC EDGAR fetch failed: {sec['fetch_error']['message'][:80]}")
    if sec.get("status") == "not_configured" or sec.get("config_note"):
        notices.append(sec.get("config_note") or "SEC filings feed not configured.")

    out = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": not issues,
           "issues": issues, "notices": notices, "thresholds": CFG, "step_outcomes": steps}
    (PROC / "health.json").write_text(json.dumps(out, indent=2) + "\n")
    print("Health:", "OK" if not issues else f"{len(issues)} issue(s)")
    for i in issues:
        print("  -", i)
    for n in notices:
        print("  (notice)", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
