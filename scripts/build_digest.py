#!/usr/bin/env python3
"""Build the weekly digest from data/processed/*.json.

Outputs:
  data/weekly_summary.json  structured numbers + the "This week" bullets the page shows
  summary/latest.md         <=10-line plain-language digest for Slack

Every number here is computed from the processed files; nothing is typed in.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import organ_metrics, total_series  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
SUMMARY_JSON = ROOT / "data" / "weekly_summary.json"
SUMMARY_MD = ROOT / "summary" / "latest.md"
SITE_URL = "https://emmania1.github.io/srta-transplant-tracker/"

ORGANS = ["heart", "liver", "lung", "kidney"]
# Headline relevance: lower = more relevant to SRTA
GROUP_PRIORITY = {"strata": 0, "volumes": 1, "competitors": 2, "opo_regulation": 3,
                  "tech_logistics": 4}
MAX_LINES = 10


def load(name):
    p = PROC / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else {"status": "awaiting_data"}


def arrow(p):
    if p is None:
        return "n/a"
    if p > 0:
        return f"▲ {p:.1f}%"
    if p < 0:
        return f"▼ {abs(p):.1f}%"
    return "— 0.0%"


def fmt_date(s):
    dt = date.fromisoformat(s[:10])
    return dt.strftime("%b %-d, %Y")


def is_recent(as_of, now):
    """True when an OPTN file downloaded in the last 7 days fed this output."""
    return bool(as_of) and date.fromisoformat(as_of) > now.date() - timedelta(days=7)


def price_block(price):
    hist = price.get("history") or []
    if not hist:
        return None
    last = hist[-1]
    target = date.fromisoformat(last["date"]) - timedelta(days=7)
    base = next((h for h in reversed(hist) if date.fromisoformat(h["date"]) <= target), None)
    chg = round((last["close"] / base["close"] - 1) * 100, 1) if base else None
    return {"close": last["close"], "date": last["date"],
            "week_ago_close": base["close"] if base else None,
            "week_ago_date": base["date"] if base else None,
            "change_1w_pct": chg, "stale": bool(price.get("fetch_error")),
            "source": price.get("source")}


def mix_block(mix, dist):
    """Monthly OPTN national data: DCD share and long-distance share, current YTD vs prior
    full year (a mix comparison; the reports are annual-only)."""
    if mix.get("status") != "ok" or dist.get("status") != "ok":
        return None
    cy, py = str(mix["current_year"]), str(mix["prior_year"])

    def pair(cur, pri):
        return {"current": cur, "prior": pri,
                "change_pts": round(cur - pri, 1) if cur is not None and pri is not None else None}
    return {
        "current_label": mix["current_label"], "prior_label": mix["prior_label"],
        "period_end": mix["period_end"], "snapshot_downloaded": mix.get("snapshot_downloaded"),
        "comparison_note": mix["comparison_note"],
        "dcd_share_donors": pair(mix["donors"][cy]["dcd_share_pct"], mix["donors"][py]["dcd_share_pct"]),
        "dcd_share_by_organ": {o: pair(v[cy]["dcd_share_pct"], v[py]["dcd_share_pct"])
                               for o, v in mix["transplants_by_organ"].items()},
        "long_bands": dist["long_bands"],
        "long_share_by_organ": {o: pair(v[cy]["long_share_pct"], v[py]["long_share_pct"])
                                for o, v in dist["organs"].items()},
    }


def regions_block(rw):
    if rw.get("status") != "ok":
        return None
    out = {r: organ_metrics(rows) for r, rows in rw["regions"].items()}
    return {"data_as_of": rw.get("data_as_of"), "regions": out}


def pts(v):
    return "n/a" if v is None else f"{'+' if v > 0 else ''}{v:.1f} pts"


def news_block(news, now):
    items = news.get("items") or []
    labels = {g["id"]: g["label"] for g in news.get("groups", [])}
    week_ago = now - timedelta(days=7)
    new = [i for i in items if i.get("first_seen") and datetime.fromisoformat(i["first_seen"]) >= week_ago
           and datetime.fromisoformat(i["date"]) >= week_ago]
    counts = {gid: 0 for gid in labels}
    for i in new:
        for t in i["tags"]:
            counts[t] = counts.get(t, 0) + 1
    ranked = sorted(new, key=lambda i: (min(GROUP_PRIORITY.get(t, 9) for t in i["tags"]),
                                        -datetime.fromisoformat(i["date"]).timestamp()))
    top = [{"headline": i["headline"], "source": i["source"], "date": i["date"][:10],
            "url": i["url"], "tags": i["tags"]} for i in ranked[:5]]
    return {"new_items_7d": len(new), "by_category": counts, "labels": labels, "top_headlines": top,
            "fetched_at": news.get("fetched_at")}


def main():
    now = datetime.now(timezone.utc)
    tw = load("transplants_weekly")
    dw = load("donors_weekly")
    price = price_block(load("price"))
    mix = mix_block(load("donor_mix"), load("distance"))
    loc = load("location")
    regions = regions_block(load("regions_weekly"))
    news = news_block(load("news"), now)

    optn_ok = tw.get("status") == "ok"
    organs = {}
    total = None
    if optn_ok:
        series = tw.get("organs", {})
        organs = {o: organ_metrics(series.get(o) or []) for o in ORGANS}
        total = organ_metrics(series["all"]) if series.get("all") else \
            organ_metrics(total_series({o: series.get(o) or [] for o in ORGANS}))
    donors = None
    if dw.get("status") == "ok":
        tbl = dw.get("ytd_table") or []
        cur = tbl[-1] if tbl else None
        prior = next((r for r in tbl if cur and r["yr"] == cur["yr"] - 1), None)
        donors = {"metrics": organ_metrics(dw.get("donors") or []),
                  "discard": None if not cur else {
                      "year": cur["yr"], "through": dw.get("ytd_through"),
                      "discard_rate_pct": cur["discard_rate_pct"],
                      "prior_year_discard_rate_pct": prior["discard_rate_pct"] if prior else None,
                      "change_pts": round(cur["discard_rate_pct"] - prior["discard_rate_pct"], 2) if prior else None}}
    as_of = tw.get("data_as_of")
    new_optn = bool(optn_ok and is_recent(as_of, now))

    # ---- plain-language lines (shared by page "This week" box and Slack digest)
    bullets = []
    if not optn_ok:
        bullets.append("OPTN volumes: awaiting first data file — no transplant figures loaded yet.")
    else:
        if not new_optn:
            bullets.append(f"No new OPTN data arrived this week; volumes below are from the {fmt_date(as_of)} pull.")
        parts = []
        for o in ORGANS:
            m = organs.get(o)
            t4 = (m or {}).get("trailing_4wk") or {}
            parts.append(f"{o.title()} {arrow(t4.get('yoy_pct'))}")
        bullets.append("Transplants, last 4 complete weeks vs same weeks last year: " + " · ".join(parts) + ".")
        parts = []
        for o in ORGANS:
            ytd = ((organs.get(o) or {}).get("ytd")) or {}
            parts.append(f"{o.title()} {arrow(ytd.get('yoy_pct'))}")
        lw = (total or {}).get("latest_week") or next(
            (organs[o]["latest_week"] for o in ORGANS if organs.get(o)), {})
        through = f" (through week ending {fmt_date(lw['week_end'])})" if lw else ""
        bullets.append("Year to date vs last year" + through + ": " + " · ".join(parts) + ".")

    if donors and donors["metrics"]:
        t4 = donors["metrics"].get("trailing_4wk") or {}
        line = f"Deceased donors recovered, last 4 complete weeks vs last year: {arrow(t4.get('yoy_pct'))}"
        disc = donors["discard"]
        if disc and disc["change_pts"] is not None:
            line += (f"; all-organs discard rate {disc['discard_rate_pct']:.1f}% YTD through {disc['through']}"
                     f" vs {disc['prior_year_discard_rate_pct']:.1f}% a year ago")
        bullets.append(line + ".")

    if mix and is_recent(mix.get("snapshot_downloaded"), now):
        # new monthly OPTN national snapshot this week
        d = mix["dcd_share_donors"]
        lb = " · ".join(f"{o.title()} {v['current']}% ({pts(v['change_pts'])})"
                        for o, v in mix["long_share_by_organ"].items())
        bullets.append(f"New OPTN monthly data ({mix['current_label']} vs {mix['prior_label']}, mix comparison): "
                       f"DCD {d['current']}% of deceased donors ({pts(d['change_pts'])}); "
                       f"transplants travelling 251+ NM: {lb}.")

    if news["new_items_7d"]:
        cats = [f"{news['labels'].get(k, k)} {v}" for k, v in news["by_category"].items() if v]
        n = news["new_items_7d"]
        news_line = (f"{n} new news item{'s' if n != 1 else ''} this week — " + ", ".join(cats) + ".")
    else:
        news_line = "No new news items matched the keyword groups this week."

    # ---- Slack markdown, capped at MAX_LINES
    week_label = now.date().isoformat()
    head = f"*SRTA Transplant Tracker — week of {fmt_date(week_label)}*"
    if price:
        head += f" · SRTA ${price['close']:.2f} ({arrow(price['change_1w_pct'])} 1-wk)"
    lines = [head] + [f"• {b}" for b in bullets]
    room = MAX_LINES - len(lines) - 1  # "Top headlines:" line
    heads = news["top_headlines"][:max(0, min(5, room))]
    if heads:
        lines.append(f"Headlines ({news_line.rstrip('.').replace(' — ', ': ')}):")
        lines += [f"  – <{h['url']}|{h['headline']}> ({h['source']}, {h['date']})" for h in heads]
    else:
        lines.append(news_line)
    if len(lines) < MAX_LINES:
        lines.append(f"Dashboard: {SITE_URL}")
    lines = lines[:MAX_LINES]

    summary = {
        "generated_at": now.isoformat(timespec="seconds"),
        "price": price,
        "optn": {"status": tw.get("status"), "data_as_of": as_of, "raw_file": tw.get("raw_file"),
                 "new_data_this_week": new_optn, "organs": organs, "all_organs": total},
        "donors": donors,
        "donor_mix_and_distance": mix,
        "regions": regions,
        "location": {"status": loc.get("status"), "period_end": loc.get("period_end"),
                     "yoy_available": loc.get("yoy_available"), "yoy_note": loc.get("yoy_note")},
        "news": news,
        "bullets": bullets,
        "news_line": news_line,
        "markdown_lines": lines,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2) + "\n")
    SUMMARY_MD.parent.mkdir(exist_ok=True)
    SUMMARY_MD.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
