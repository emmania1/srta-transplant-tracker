"""Shared week handling + YoY math. Used by ingest_optn.py and build_digest.py.

Normalized weekly row: {"week_start": "YYYY-MM-DD", "week_end": "YYYY-MM-DD", "count": int}

Weeks are matched year-over-year by ISO week number (of the week's midpoint,
so it works whether OPTN weeks start Sunday or Monday). Week N of this year is
compared with week N of last year; ISO week 53 has no prior-year match.
"""
from datetime import date, timedelta


def d(s):
    return date.fromisoformat(s)


def iso_key(row):
    mid = d(row["week_start"]) + timedelta(days=3)
    y, w, _ = mid.isocalendar()
    return (y, w)


def drop_incomplete(rows, as_of):
    """Keep only weeks that ended strictly before `as_of` (the data pull date).

    OPTN's current week is partial and shows as a sharp drop. A week ending on
    the pull date itself is also dropped, since the pull may predate that day's
    reporting. Returns (kept, dropped).
    """
    kept, dropped = [], []
    for r in rows:
        (kept if d(r["week_end"]) < as_of else dropped).append(r)
    return kept, dropped


def pct(cur, prior):
    if cur is None or prior in (None, 0):
        return None
    return round((cur / prior - 1) * 100, 1)


def organ_metrics(rows):
    """rows: complete weeks for one organ, any order. Returns card metrics + workings."""
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r["week_start"])
    by_key = {iso_key(r): r for r in rows}
    latest = rows[-1]
    ly, lw = iso_key(latest)

    # Same week last year
    ly_row = by_key.get((ly - 1, lw))
    week = {
        "week_start": latest["week_start"], "week_end": latest["week_end"],
        "iso_week": lw, "count": latest["count"],
        "prior_year_count": ly_row["count"] if ly_row else None,
        "yoy_pct": pct(latest["count"], ly_row["count"] if ly_row else None),
    }

    # Trailing 4 complete weeks vs the same 4 ISO weeks last year
    last4 = rows[-4:]
    t4 = None
    if len(last4) == 4:
        keys = [iso_key(r) for r in last4]
        prior = [by_key.get((y - 1, w)) for (y, w) in keys]
        cur_sum = sum(r["count"] for r in last4)
        prior_sum = sum(p["count"] for p in prior) if all(prior) else None
        t4 = {
            "weeks": [f"{y}-W{w:02d}" for (y, w) in keys],
            "total": cur_sum,
            "prior_year_total": prior_sum,
            "yoy_pct": pct(cur_sum, prior_sum),
        }

    # Year-to-date through the latest ISO week vs the same span last year
    cur_ytd_rows = [r for r in rows if iso_key(r)[0] == ly and iso_key(r)[1] <= lw]
    prior_ytd_rows = [r for r in rows if iso_key(r)[0] == ly - 1 and iso_key(r)[1] <= lw]
    cur_ytd = sum(r["count"] for r in cur_ytd_rows)
    # Only compare when both spans are fully covered (no missing weeks)
    full = len(cur_ytd_rows) == lw and len(prior_ytd_rows) == lw
    prior_ytd = sum(r["count"] for r in prior_ytd_rows) if full else None
    ytd = {
        "through_iso_week": lw, "year": ly,
        "total": cur_ytd if len(cur_ytd_rows) == lw else None,
        "prior_year_total": prior_ytd,
        "yoy_pct": pct(cur_ytd, prior_ytd) if full else None,
        "weeks_covered": len(cur_ytd_rows), "prior_weeks_covered": len(prior_ytd_rows),
    }
    return {"latest_week": week, "trailing_4wk": t4, "ytd": ytd}


def total_series(organs):
    """Sum organs per week, only for weeks where every organ has a value."""
    names = [k for k, v in organs.items() if v]
    if not names:
        return []
    maps = {n: {r["week_start"]: r for r in organs[n]} for n in names}
    common = set.intersection(*(set(m) for m in maps.values()))
    out = []
    for ws in sorted(common):
        first = maps[names[0]][ws]
        out.append({"week_start": ws, "week_end": first["week_end"],
                    "count": sum(maps[n][ws]["count"] for n in names)})
    return out
