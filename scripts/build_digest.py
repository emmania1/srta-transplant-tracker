#!/usr/bin/env python3
"""Build the weekly digest from data/processed/*.json.

Outputs:
  data/weekly_summary.json  structured numbers + the "This week" bullets the page shows
  summary/latest.md         <=10-line plain-language digest for Slack

Every number here is computed from the processed files; nothing is typed in.
"""
import json
import re
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
KEYWORDS = ROOT / "config" / "keywords.json"
HOLDINGS = ROOT / "config" / "holdings.json"
SIGNALS = ROOT / "config" / "signals.json"
ORGAN_LABEL = {"heart": "Heart", "liver": "Liver", "lung": "Lung", "kidney": "Kidney (incl. KP)"}
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


def price_block(t):
    """Last close + 1-week change for one ticker entry of price.json."""
    hist = (t or {}).get("history") or []
    if not hist:
        return None
    last = hist[-1]
    target = date.fromisoformat(last["date"]) - timedelta(days=7)
    base = next((h for h in reversed(hist) if date.fromisoformat(h["date"]) <= target), None)
    chg = round((last["close"] / base["close"] - 1) * 100, 1) if base else None
    return {"close": last["close"], "date": last["date"],
            "week_ago_close": base["close"] if base else None,
            "week_ago_date": base["date"] if base else None,
            "change_1w_pct": chg, "stale": bool(t.get("fetch_error"))}


def prices_block(price):
    tick = price.get("tickers") or {}
    out = {sym: price_block(v) for sym, v in tick.items()}
    hold = json.loads(HOLDINGS.read_text())["joby_contingent"]
    j = out.get("JOBY")
    joby = None
    if j:
        joby = {"shares": hold["shares"], "label": hold["label"], "source": hold["source"],
                "source_url": hold.get("source_url"), "tag": hold["tag"],
                "value": round(j["close"] * hold["shares"]),
                "value_week_ago": round(j["week_ago_close"] * hold["shares"]) if j["week_ago_close"] else None,
                "change_1w_pct": j["change_1w_pct"], "price_date": j["date"]}
    # SRTA vs TMDX, 3 months, both indexed to 100 on the first common date
    rel = None
    s_h = {h["date"]: h["close"] for h in (tick.get("SRTA") or {}).get("history", [])}
    t_h = {h["date"]: h["close"] for h in (tick.get("TMDX") or {}).get("history", [])}
    common = sorted(set(s_h) & set(t_h))
    if common:
        start = (date.fromisoformat(common[-1]) - timedelta(days=91)).isoformat()
        dates = [d for d in common if d >= start]
        b_s, b_t = s_h[dates[0]], t_h[dates[0]]
        rel = {"base_date": dates[0], "dates": dates,
               "SRTA": [round(100 * s_h[d] / b_s, 2) for d in dates],
               "TMDX": [round(100 * t_h[d] / b_t, 2) for d in dates]}
        rel["srta_minus_tmdx_pts"] = round(rel["SRTA"][-1] - rel["TMDX"][-1], 1)
    return {"tickers": out, "joby": joby, "relative_3m": rel, "source": price.get("source")}



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
    """News counts for the week + digest headline picks ranked by relevance (config/keywords.json 'digest')."""
    items = news.get("items") or []
    labels = {g["id"]: g["label"] for g in news.get("groups", [])}
    cfg = json.loads(KEYWORDS.read_text()).get("digest", {})
    week_ago = now - timedelta(days=7)
    new = [i for i in items if datetime.fromisoformat(i["date"]) >= week_ago]
    counts = {gid: 0 for gid in labels}
    for i in new:
        for t in i["tags"]:
            counts[t] = counts.get(t, 0) + 1

    prio = {g: n for n, g in enumerate(cfg.get("priority", []))}
    # word-start match so 'opo' doesn't hit 'proposal'; plurals still match ('transplant' -> 'transplants')
    angle = [re.compile(r"\b" + re.escape(a), re.I) for a in cfg.get("angle_terms", [])]
    excl = [re.compile(x, re.I) for x in cfg.get("exclude_patterns", [])]

    def eligible(i, days):
        h = i["headline"]
        return (datetime.fromisoformat(i["date"]) >= now - timedelta(days=days)
                and any(a.search(h) for a in angle) and not any(p.search(h) for p in excl))

    def rank(pool):
        return sorted(pool, key=lambda i: (min(prio.get(t, 99) for t in i["tags"]),
                                           -datetime.fromisoformat(i["date"]).timestamp()))
    max_n, min_n = cfg.get("max_items", 5), cfg.get("min_items", 3)
    picks = rank([i for i in items if eligible(i, cfg.get("primary_days", 7))])[:max_n]
    if len(picks) < min_n:
        seen = {i["url"] for i in picks}
        more = rank([i for i in items if i["url"] not in seen and eligible(i, cfg.get("fallback_days", 14))])
        picks = rank(picks + more[:min_n - len(picks)])
    top = [{"headline": i["headline"], "source": i["source"], "date": i["date"][:10],
            "url": i.get("publisher_url") or i["url"], "google_url": i["url"], "tags": i["tags"]} for i in picks]
    return {"new_items_7d": len(new), "by_category": counts, "labels": labels, "top_headlines": top,
            "fetched_at": news.get("fetched_at")}


def classify(v, band, labels):
    if v is None:
        return None
    return labels["up"] if v > band else labels["down"] if v < -band else labels["flat"]


def signals_block(organs, mix, donors):
    cfg = json.loads(SIGNALS.read_text())
    out = {"thresholds": cfg}
    c = cfg["volumes"]
    out["volumes"] = {o: {"value": ((organs.get(o) or {}).get("trailing_4wk") or {}).get("yoy_pct"), "unit": "%"}
                      for o in ORGANS}
    for v in out["volumes"].values():
        v["label"] = classify(v["value"], c["flat_within_pct"], c["labels"])
    if mix:
        c = cfg["distance"]
        out["distance"] = {o: {"value": v["change_pts"], "unit": "pts",
                               "label": classify(v["change_pts"], c["flat_within_pts"], c["labels"])}
                           for o, v in mix["long_share_by_organ"].items()}
        c = cfg["dcd_share"]
        d = mix["dcd_share_donors"]
        out["dcd_share"] = {"value": d["change_pts"], "unit": "pts", "current": d["current"],
                            "label": classify(d["change_pts"], c["flat_within_pts"], c["labels"]),
                            "basis": f"{mix['current_label']} vs {mix['prior_label']}"}
    disc = (donors or {}).get("discard")
    if disc and disc["change_pts"] is not None:
        c = cfg["discard_rate"]
        out["discard_rate"] = {"value": disc["change_pts"], "unit": "pts", "current": disc["discard_rate_pct"],
                               "label": classify(disc["change_pts"], c["flat_within_pts"], c["labels"]),
                               "basis": f"YTD through {disc['through']} vs same period last year"}
    return out


def signals_line(sig):
    def num(v, unit):
        if v is None:
            return "n/a"
        return f"{'+' if v > 0 else ''}{v:.1f}{'%' if unit == '%' else ' pts'}"
    parts = ["Volumes " + ", ".join(f"{ORGAN_LABEL[o].split(' (')[0]} {v['label'] or 'n/a'} ({num(v['value'], '%')})"
                                    for o, v in sig["volumes"].items())]
    if sig.get("distance"):
        parts.append("Distance " + ", ".join(f"{o.title()} {v['label']}" for o, v in sig["distance"].items()))
    if sig.get("dcd_share"):
        parts.append(f"DCD share {sig['dcd_share']['label']} ({num(sig['dcd_share']['value'], 'pts')})")
    if sig.get("discard_rate"):
        parts.append(f"Discard rate {sig['discard_rate']['label']} ({num(sig['discard_rate']['value'], 'pts')})")
    return "Signals: " + " | ".join(parts) + "."


def sec_block(sec, now):
    if sec.get("status") != "ok":
        return None
    week_ago = (now.date() - timedelta(days=7)).isoformat()
    fl = sec.get("filings") or []
    sales = [f for f in fl if (f.get("form4") or {}).get("open_market_sale")]
    d13 = [f for f in fl if "13D" in f["form"]]
    return {"count": len(fl), "fetched_at": sec.get("fetched_at"),
            "form4_sales": [{"filed": f["filed"], "owner": f["form4"]["owner"], "roles": f["form4"]["roles"],
                             "shares_sold": f["form4"]["shares_sold"], "url": f["url"]} for f in sales],
            "schedule_13d": [{"filed": f["filed"], "form": f["form"], "url": f["url"]} for f in d13],
            "new_this_week": [f for f in fl if f["filed"] >= week_ago]}


def wl_block(wl):
    if wl.get("status") != "ok":
        return None
    return {o: organ_metrics(rows) for o, rows in wl["organs"].items()}


def cdc_block(cdc):
    s = (cdc or {}).get("series") or []
    if not s:
        return None
    last = s[-1]
    return {"period_end": last["period_end"], "predicted": last["predicted"], "reported": last["reported"],
            "predicted_yoy_pct": last["predicted_yoy_pct"], "reported_yoy_pct": last["reported_yoy_pct"],
            "dataset_updated": cdc.get("dataset_updated")}


def main():
    now = datetime.now(timezone.utc)
    tw = load("transplants_weekly")
    dw = load("donors_weekly")
    prices = prices_block(load("price"))
    srta = prices["tickers"].get("SRTA")
    mix = mix_block(load("donor_mix"), load("distance"))
    loc = load("location")
    regions = regions_block(load("regions_weekly"))
    news = news_block(load("news"), now)
    health = load("health")
    sec = sec_block(load("sec_filings"), now)
    waitlist = wl_block(load("waitlist_weekly"))
    cdc = cdc_block(load("cdc_overdose"))

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
    signals = signals_block(organs, mix, donors) if optn_ok else None

    # ---- plain-language lines (shared by page "This week" box and Slack digest)
    issues = (health or {}).get("issues") or []
    issue_line = ("Data issue: " + " ".join(issues)) if issues else None
    bullets = []
    if not optn_ok:
        bullets.append("OPTN volumes: awaiting first data file — no transplant figures loaded yet.")
    else:
        if not new_optn:
            bullets.append(f"No new OPTN data arrived this week; volumes below are from the {fmt_date(as_of)} pull.")
        lw = (total or {}).get("latest_week") or next(
            (organs[o]["latest_week"] for o in ORGANS if organs.get(o)), {})
        parts = [f"{ORGAN_LABEL[o]} {arrow(((organs.get(o) or {}).get('trailing_4wk') or {}).get('yoy_pct'))} / "
                 f"{arrow(((organs.get(o) or {}).get('ytd') or {}).get('yoy_pct'))}" for o in ORGANS]
        bullets.append(f"Transplants vs last year, last 4 weeks / YTD (through week ending {fmt_date(lw['week_end'])}): "
                       + " · ".join(parts) + ".")
        bullets.append(signals_line(signals))

    if donors and donors["metrics"]:
        t4 = donors["metrics"].get("trailing_4wk") or {}
        line = f"Deceased donors recovered, last 4 weeks vs last year: {arrow(t4.get('yoy_pct'))}"
        disc = donors["discard"]
        if disc and disc["change_pts"] is not None:
            line += (f"; all-organs discard rate {disc['discard_rate_pct']:.1f}% YTD through {disc['through']}"
                     f" vs {disc['prior_year_discard_rate_pct']:.1f}% a year ago")
        bullets.append(line + ".")

    # optional lines, in priority order, while there is room (max 5 bullets, 4 with a data-issue line)
    optional = []
    if sec:
        flags = [f for f in sec["form4_sales"] if f["filed"] >= (now.date() - timedelta(days=7)).isoformat()]
        d13 = [f for f in sec["schedule_13d"] if f["filed"] >= (now.date() - timedelta(days=7)).isoformat()]
        if flags or d13:
            bits = [f"Form 4 sale: {f['owner']} ({', '.join(f['roles']) or 'insider'}) sold {f['shares_sold']:,.0f} sh, filed {f['filed']}"
                    for f in flags] + [f"{f['form']} filed {f['filed']}" for f in d13]
            optional.append("SEC: " + "; ".join(bits) + ".")
    if mix and is_recent(mix.get("snapshot_downloaded"), now):
        d = mix["dcd_share_donors"]
        lb = " · ".join(f"{o.title()} {v['current']}% ({pts(v['change_pts'])})"
                        for o, v in mix["long_share_by_organ"].items())
        optional.append(f"New OPTN monthly data ({mix['current_label']} vs {mix['prior_label']}, mix comparison): "
                        f"DCD {d['current']}% of deceased donors ({pts(d['change_pts'])}); 251+ NM share: {lb}.")
    if waitlist:
        optional.append("Waitlist additions, last 4 weeks vs last year: " + " · ".join(
            f"{ORGAN_LABEL[o]} {arrow(((waitlist.get(o) or {}).get('trailing_4wk') or {}).get('yoy_pct'))}" for o in ORGANS) + ".")
    max_bullets = 4 if issue_line else 5
    bullets += optional[:max(0, max_bullets - len(bullets))]

    if news["new_items_7d"]:
        cats = [f"{news['labels'].get(k, k)} {v}" for k, v in news["by_category"].items() if v]
        n = news["new_items_7d"]
        news_line = (f"{n} new news item{'s' if n != 1 else ''} this week — " + ", ".join(cats) + ".")
    else:
        news_line = "No new news items matched the keyword groups this week."

    # ---- Slack markdown, capped at MAX_LINES
    head = f"*SRTA Transplant Tracker — week of {fmt_date(now.date().isoformat())}*"
    if srta:
        head += f" · SRTA ${srta['close']:.2f} ({arrow(srta['change_1w_pct'])} 1-wk)"
    lines = ([f"⚠️ {issue_line}"] if issue_line else []) + [head] + [f"• {b}" for b in bullets]
    room = MAX_LINES - len(lines) - 1  # headlines header line
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
        "price": srta, "prices": prices,
        "health": health,
        "optn": {"status": tw.get("status"), "data_as_of": as_of, "raw_file": tw.get("raw_file"),
                 "new_data_this_week": new_optn, "organs": organs, "all_organs": total},
        "donors": donors,
        "signals": signals,
        "waitlist": waitlist,
        "cdc_overdose": cdc,
        "sec": sec,
        "donor_mix_and_distance": mix,
        "regions": regions,
        "location": {"status": loc.get("status"), "period_end": loc.get("period_end"),
                     "yoy_available": loc.get("yoy_available"), "yoy_note": loc.get("yoy_note")},
        "news": news,
        "issue_line": issue_line,
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
