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
from quarters import quarter_metrics  # noqa: E402

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
MAX_LINES = 13  # title + up to 7 labelled bullets + 'Top headlines' + 3 headlines + link
CORE = "hll"
CORE_LABEL = "Heart + liver + lung (Strata's core flying organs)"
CORE_SHORT = "heart+liver+lung"


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
                "cap_contingent_usd": hold.get("cap_contingent_usd"), "cap_holdback_usd": hold.get("cap_holdback_usd"),
                "cap_source": hold.get("cap_source"),
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


def latest_results_filing(sec_raw):
    """Filing date of SRTA's most recent results 8-K (item 2.02), from sec_filings.json."""
    dates = [f["filed"] for f in (sec_raw or {}).get("filings", [])
             if f["form"].startswith("8-K") and "2.02" in (f.get("items") or "")]
    return max(dates) if dates else None


def news_block(news, now, sec_raw=None):
    """News counts for the week + digest headline picks ranked by relevance (config/keywords.json 'digest').

    Never picked: opinion-tagged items, corporate housekeeping (digest.exclude_patterns), items with no
    industry angle, and SRTA results reprints dated more than stale_results.max_days after SRTA's latest
    results 8-K. If fewer than min_items_or_none good items remain, there are no picks (the digest says
    none_text instead of padding)."""
    items = news.get("items") or []
    labels = {g["id"]: g["label"] for g in news.get("groups", [])}
    kcfg = json.loads(KEYWORDS.read_text())
    cfg = kcfg.get("digest", {})
    op_tag = (kcfg.get("opinion") or {}).get("tag", "opinion")
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
    sr = cfg.get("stale_results") or {}
    sr_pats = [re.compile(x, re.I) for x in sr.get("patterns", [])]
    sr_cos = [re.compile(r"\b" + re.escape(x), re.I) for x in sr.get("company_terms", [])]
    results_filed = latest_results_filing(sec_raw)

    def stale_results(i):
        h = i["headline"]
        if not results_filed or not any(p.search(h) for p in sr_pats) or not any(c.search(h) for c in sr_cos):
            return False
        return (date.fromisoformat(i["date"][:10]) - date.fromisoformat(results_filed)).days > sr.get("max_days", 14)

    def eligible(i, days):
        h = i["headline"]
        return (datetime.fromisoformat(i["date"]) >= now - timedelta(days=days)
                and op_tag not in i["tags"]
                and any(a.search(h) for a in angle) and not any(p.search(h) for p in excl)
                and not stale_results(i))

    def rank(pool):
        return sorted(pool, key=lambda i: (min(prio.get(t, 99) for t in i["tags"]),
                                           -datetime.fromisoformat(i["date"]).timestamp()))
    max_n, min_n = cfg.get("max_items", 3), cfg.get("min_items", 3)
    picks = rank([i for i in items if eligible(i, cfg.get("primary_days", 7))])[:max_n]
    if len(picks) < min_n:
        seen = {i["url"] for i in picks}
        more = rank([i for i in items if i["url"] not in seen and eligible(i, cfg.get("fallback_days", 14))])
        picks = rank(picks + more[:min_n - len(picks)])
    if len(picks) < cfg.get("min_items_or_none", 2):
        picks = []
    top = [{"headline": i["headline"], "source": i["source"], "date": i["date"][:10],
            "url": i.get("publisher_url") or i["url"], "google_url": i["url"], "tags": i["tags"]} for i in picks]
    return {"new_items_7d": len(new), "by_category": counts, "labels": labels, "top_headlines": top,
            "none_text": cfg.get("none_text", "No major news this week") if not top else None,
            "fetched_at": news.get("fetched_at")}


# ---- plain-English "This week" sentences (the page shows these verbatim) ----
def join_list(xs):
    xs = list(xs)
    return "".join(xs) if len(xs) <= 1 else f"{xs[0]} and {xs[1]}" if len(xs) == 2 else f"{', '.join(xs[:-1])} and {xs[-1]}"


def direction_sentence(items, noun, period):
    """items in display order: (name, value, label up|flat|down) ->
    'Heart and kidney transplants fell 5.8% and 2.1% over ...; liver and lung rose 6.8% and 5.4%.'"""
    order, groups = [], {}
    for name, v, label in items:
        if v is None:
            continue
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append((name, v))
    if not order:
        return None
    parts = []
    for idx, k in enumerate(order):
        g = groups[k]
        names = join_list(n if (idx == 0 and j == 0) else n.lower() for j, (n, _) in enumerate(g))
        n_ = noun if idx == 0 else ""
        p_ = period if idx == 0 else ""
        if k == "flat":
            verb = "were" if len(g) > 1 or n_ else "was"
            vals = ", ".join(f"{'+' if v > 0 else ''}{v:.1f}%" for _, v in g)
            parts.append(f"{names}{n_} {verb} roughly flat{p_} ({vals})")
        else:
            parts.append(f"{names}{n_} {'rose' if k == 'up' else 'fell'} {join_list(f'{abs(v):.1f}%' for _, v in g)}{p_}")
    return "; ".join(parts) + "."


def f4_who(owner, roles):
    last = (owner or "").replace(",", " ").split()
    name = last[0][0] + last[0][1:].lower() if last else "Insider"
    role = next((r for r in roles if r not in ("Director", "10% owner")), roles[0] if roles else "insider")
    return f"{name} ({role.replace(' and ', '/')})"


def arrow_pct(v):
    return "n/a" if v is None else f"{'▲' if v > 0 else '▼' if v < 0 else '—'} {abs(v):.1f}%"


def quarterly_block(series):
    """Last complete calendar quarter (prorated boundary weeks) for each organ + heart+liver+lung."""
    rows_all = [r for k in ORGANS + [CORE] for r in series.get(k) or []]
    if not rows_all:
        return None
    last = max(date.fromisoformat(r["week_end"]) for r in rows_all)
    out = {k: quarter_metrics(series[k], last) for k in [CORE] + ORGANS if series.get(k)}
    return {"last_complete_day": last.isoformat(), "organs": out,
            "note": ("Calendar quarters (Jan 1–Mar 31 etc.). OPTN weeks don't line up with quarter ends, so a week "
                     "that straddles a boundary is split by days (its count spread evenly over its 7 days). "
                     "Typical seasonal change = average of the same quarter-over-quarter change in the prior 3 years. "
                     "Recent weeks may be revised up as centers finish reporting.")}


def labelled_bullets(signals, donors, mix, waitlist, sec, quarterly, regions, optn_ok, new_optn, now, through):
    """Bullets shared by the page's "This week" box and the Slack digest.
    Each: {label, text, through (date str or None), page (shown on the page; Signals is digest-only
    because the page shows the signal chips)}."""
    out = []
    band = (signals or {}).get("thresholds", {}).get("volumes", {}).get("flat_within_pct", 2)
    lab = lambda v: "flat" if v is None else "up" if v > band else "down" if v < -band else "flat"  # noqa: E731
    if optn_ok and not new_optn:
        out.append({"label": "Data", "text": "No new OPTN weekly data arrived this week, so transplant figures are unchanged.",
                    "through": through.get("weekly"), "page": True})
    if signals and signals.get("volumes"):
        core = signals["volumes"].get(CORE, {})
        lead = (f"{CORE_LABEL} {'rose' if core['value'] > 0 else 'fell'} {abs(core['value']):.1f}% over the last 4 weeks vs. last year"
                if core.get("value") is not None else "")
        by = direction_sentence([(o.title(), signals["volumes"][o]["value"], signals["volumes"][o]["label"]) for o in ORGANS], "", "")
        text = f"{lead}; by organ, {by[0].lower() + by[1:]}" if lead and by else (lead + "." if lead else by)
        out.append({"label": "Volumes", "text": text, "through": through.get("weekly"), "page": True})
    if quarterly and quarterly["organs"].get(CORE):
        m = quarterly["organs"][CORE]
        qn, pqn = m["quarter"].split()[0], m["prior_quarter"].split()[0]
        text = (f"{qn} {CORE_SHORT} {arrow_pct(m['yoy_pct'])} YoY; {arrow_pct(m['seq_pct'])} vs {pqn} "
                f"(typical {pqn}→{qn}: {arrow_pct(m['typical_seq_pct'])})")
        if m["qtd"]["shown"]:
            text += f"; {m['qtd']['quarter'].split()[0]} to date {arrow_pct(m['qtd']['yoy_pct'])} YoY"
        out.append({"label": "Quarter", "text": text + ".", "through": fmt_date(m["end"]), "page": True})
    if donors and donors.get("metrics") and donors["metrics"].get("trailing_4wk"):
        v = donors["metrics"]["trailing_4wk"]["yoy_pct"]
        t = f"Deceased donors recovered {'rose' if v > 0 else 'fell' if v < 0 else 'were flat at'} {abs(v):.1f}% over the last 4 weeks vs. last year"
        d = donors.get("discard")
        if d and d.get("prior_year_discard_rate_pct") is not None:
            t += (f", and {d['discard_rate_pct']:.1f}% of recovered organs have been discarded so far this year "
                  f"({d['prior_year_discard_rate_pct']:.1f}% a year earlier)")
        out.append({"label": "Donors", "text": t + ".", "through": through.get("donors"), "page": True})
    if mix and signals and signals.get("distance"):
        d0 = mix["dcd_share_donors"]
        longer = [o for o in ORGANS if signals["distance"][o]["label"] == "longer"]
        shorter = [o for o in ORGANS if signals["distance"][o]["label"] == "shorter"]
        if not longer and not shorter:
            dist = "the share of organs travelling 251+ NM held steady for every organ"
        else:
            bits = ([f"rose for {join_list(longer)}"] if longer else []) + ([f"fell for {join_list(shorter)}"] if shorter else [])
            dist = "the share of organs travelling 251+ NM " + " and ".join(bits)
            if len(longer) + len(shorter) < len(ORGANS):
                dist += " and held steady for the rest"
        prior = d0["current"] - d0["change_pts"]
        out.append({"label": "Donor mix & distance",
                    "text": f"DCD donors are {d0['current']:.1f}% of deceased donors so far this year, "
                            f"{'up' if d0['change_pts'] >= 0 else 'down'} from {prior:.1f}% in {mix['prior_label'].replace(' full year', '')}; {dist}.",
                    "through": fmt_date(mix["period_end"]), "page": True})
    if waitlist:
        core = ((waitlist.get(CORE) or {}).get("trailing_4wk") or {}).get("yoy_pct")
        items = [(o.title(), ((waitlist.get(o) or {}).get("trailing_4wk") or {}).get("yoy_pct"), None) for o in ORGANS]
        items = [(n, v, lab(v)) for n, v, _ in items]
        by = direction_sentence(items, "", "")
        lead = f"{CORE_SHORT.capitalize()} waitlist additions {'rose' if core > band else 'fell' if core < -band else 'were roughly flat'}" \
               f"{'' if -band <= core <= band else ''} ({'+' if core > 0 else ''}{core:.1f}%) over the last 4 weeks vs. last year" if core is not None else ""
        text = f"{lead}; by organ, {by[0].lower() + by[1:]}" if lead and by else by
        out.append({"label": "Waitlist", "text": text, "through": through.get("waitlist"), "page": True})
    if regions and regions.get("regions"):
        names = regions.get("names", {})
        moves = [(r, m["trailing_4wk"]["yoy_pct"]) for r, m in regions["regions"].items()
                 if m and (m.get("trailing_4wk") or {}).get("yoy_pct") is not None]
        moves.sort(key=lambda x: -abs(x[1]))
        bits = [f"{names.get(r, 'Region ' + r)} (Region {r}) {arrow_pct(v)}" for r, v in moves[:3]]
        if bits:
            out.append({"label": "Regions", "text": "biggest moves over the last 4 weeks vs. last year: " + ", ".join(bits) + ".",
                        "through": through.get("regions"), "page": True})
    if sec:
        wk = (now.date() - timedelta(days=7)).isoformat()
        flags = [f for f in sec["form4_sales"] if f["filed"] >= wk]
        d13 = [f for f in sec["schedule_13d"] if f["filed"] >= wk]
        if flags or d13:
            bits = [f"{f4_who(f['owner'], f['roles'])} sold {f['shares_sold']:,.0f} shares on the open market" for f in flags]
            bits += [f"a {f['form']} large-holder filing was made" for f in d13]
            out.append({"label": "SEC", "text": "; ".join(bits) + ".", "through": None, "page": True})
    if signals and signals.get("volumes"):
        v = signals["volumes"]
        groups = {}
        for o in [CORE] + ORGANS:
            groups.setdefault(v[o]["label"] or "n/a", []).append(CORE_SHORT if o == CORE else o)
        vol = "; ".join(f"{k} for {join_list(g)}" for k, g in groups.items())
        parts = [f"volumes {vol}"]
        if signals.get("distance"):
            dg = {}
            for o in ORGANS:
                dg.setdefault(signals["distance"][o]["label"], []).append(o)
            parts.append("long trips (251+ NM) " + "; ".join(f"{k} for {join_list(g)}" for k, g in dg.items()))
        if signals.get("dcd_share"):
            parts.append(f"DCD share {signals['dcd_share']['label']}")
        if signals.get("discard_rate"):
            parts.append(f"discard rate {signals['discard_rate']['label']}")
        out.append({"label": "Signals", "text": " · ".join(cap_first(p) for p in parts) + ".", "through": None, "page": False})
    return out


def cap_first(t):
    return t[:1].upper() + t[1:]


def classify(v, band, labels):
    if v is None:
        return None
    return labels["up"] if v > band else labels["down"] if v < -band else labels["flat"]


def signals_block(organs, mix, donors):
    cfg = json.loads(SIGNALS.read_text())
    out = {"thresholds": cfg}
    c = cfg["volumes"]
    out["volumes"] = {o: {"value": ((organs.get(o) or {}).get("trailing_4wk") or {}).get("yoy_pct"), "unit": "%"}
                      for o in [CORE] + ORGANS}
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
    features = json.loads((ROOT / "config" / "features.json").read_text())
    # SEC feed off -> no insider line, and the stale-results rule (which needs SRTA's latest results 8-K) is off too
    sec_raw = load("sec_filings") if features.get("sec_filings") else None
    news = news_block(load("news"), now, sec_raw)
    health = load("health")
    sec = sec_block(sec_raw, now) if sec_raw else None
    waitlist = wl_block(load("waitlist_weekly"))
    cdc = cdc_block(load("cdc_overdose"))

    optn_ok = tw.get("status") == "ok"
    organs = {}
    total = None
    quarterly = None
    if optn_ok:
        series = tw.get("organs", {})
        organs = {o: organ_metrics(series.get(o) or []) for o in [CORE] + ORGANS if series.get(o)}
        quarterly = quarterly_block(series)
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

    # ---- plain-language lines (shared verbatim by the page's "This week" box and the Slack digest)
    issues = (health or {}).get("issues") or []
    issue_line = ("Data issue: " + " ".join(issues)) if issues else None
    wl_raw = load("waitlist_weekly")
    rw_raw = load("regions_weekly")
    def last_end(rows):
        return fmt_date(max(r["week_end"] for r in rows)) if rows else None
    through = {
        "weekly": last_end((tw.get("organs") or {}).get(CORE) or []),
        "donors": last_end(dw.get("donors") or []),
        "waitlist": last_end((wl_raw.get("organs") or {}).get(CORE) or []),
        "regions": last_end([r for rows in (rw_raw.get("regions") or {}).values() for r in rows]),
    }
    if regions is not None:
        regions["names"] = rw_raw.get("region_names", {})
    if not optn_ok:
        items = [{"label": "Volumes", "text": "awaiting the first OPTN data file, so no transplant figures are loaded yet.",
                  "through": None, "page": True}]
    else:
        items = labelled_bullets(signals, donors, mix, waitlist, sec, quarterly, regions, optn_ok, new_optn, now, through)
    page_items = [i for i in items if i["page"]]
    bullets = [f"{i['label']}: {i['text']}" for i in page_items]

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
    tmdx = prices["tickers"].get("TMDX")
    if tmdx:
        head += f" · TMDX ${tmdx['close']:.2f} ({arrow(tmdx['change_1w_pct'])} 1-wk)"
    lines = ([f"⚠️ {issue_line}"] if issue_line else []) + [head] + [
        f"• *{i['label']}:* {i['text']}" + (f" (data through {i['through']})" if i["through"] else "") for i in items]
    heads = news["top_headlines"]
    if heads:
        lines.append("*Top headlines:*")
        lines += [f"  – <{h['url']}|{h['headline']}> ({h['source']}, {fmt_date(h['date'])})" for h in heads]
    else:
        lines.append(f"*Top headlines:* {news['none_text']}.")
    lines.append(f"Dashboard: {SITE_URL}")
    if len(lines) > MAX_LINES:  # drop the dashboard link first, then the last headline(s)
        lines = [l for l in lines if not l.startswith("Dashboard:")][:MAX_LINES]

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
        "this_week": bullets,
        "this_week_items": items,
        "quarterly": quarterly,
        "core_label": CORE_LABEL,
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
