"""Calendar-quarter totals from OPTN weekly counts.

OPTN weeks (week 1 starts Jan 1; week 52 runs to Dec 31) don't line up with quarter
boundaries, so each week's count is spread evenly over its days and summed by calendar
date. A week that straddles a quarter boundary is split pro rata by days ("prorated").
Totals are therefore not always whole numbers.
"""
from datetime import date, timedelta

QUARTER_START = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}


def q_bounds(y, q):
    start = date(y, *QUARTER_START[q])
    end = (date(y + 1, 1, 1) if q == 4 else date(y, *QUARTER_START[q + 1])) - timedelta(days=1)
    return start, end


def prev_q(y, q):
    return (y - 1, 4) if q == 1 else (y, q - 1)


def quarter_of(d):
    return d.year, (d.month - 1) // 3 + 1


def daily(rows):
    """{date: count per day} from weekly rows (each week's count spread over its days)."""
    out = {}
    for r in rows:
        s, e = date.fromisoformat(r["week_start"]), date.fromisoformat(r["week_end"])
        n = (e - s).days + 1
        for i in range(n):
            out[s + timedelta(days=i)] = r["count"] / n
    return out


def span_total(day_map, start, end):
    """Sum over [start, end]; None unless every day in the span is covered by data."""
    total, d = 0.0, start
    while d <= end:
        if d not in day_map:
            return None
        total += day_map[d]
        d += timedelta(days=1)
    return total


def boundary_weeks(rows, start, end):
    """Weeks that straddle the span's start or end (their counts were split by day)."""
    out = []
    for r in rows:
        s, e = date.fromisoformat(r["week_start"]), date.fromisoformat(r["week_end"])
        if (s < start <= e) or (s <= end < e):
            inside = (min(e, end) - max(s, start)).days + 1
            out.append({"week": f"{r.get('yr')}-W{r.get('week'):02d}" if r.get("yr") else r["week_start"],
                        "dates": f"{s.isoformat()}..{e.isoformat()}", "days_in_span": inside,
                        "days_in_week": (e - s).days + 1, "count": r["count"]})
    return out


def pct(a, b):
    return round(100 * (a / b - 1), 1) if a is not None and b else None


def quarter_metrics(rows, last_day):
    """Metrics for the last complete calendar quarter ending on/before last_day, plus quarter-to-date."""
    dm = daily(rows)
    y, q = quarter_of(last_day)
    qs, qe = q_bounds(y, q)
    if qe != last_day:  # current quarter incomplete -> last complete one is the previous
        y, q = prev_q(y, q)
        qs, qe = q_bounds(y, q)
    py_, pq = prev_q(y, q)
    cur = span_total(dm, qs, qe)
    ly = span_total(dm, *q_bounds(y - 1, q))
    prev = span_total(dm, *q_bounds(py_, pq))
    seasonal = []
    for k in (1, 2, 3):
        a = span_total(dm, *q_bounds(y - k, q))
        b = span_total(dm, *q_bounds(*prev_q(y - k, q)))
        if a is not None and b:
            seasonal.append({"year": y - k, "seq_pct": pct(a, b)})
    typical = round(sum(s["seq_pct"] for s in seasonal) / len(seasonal), 1) if seasonal else None

    # quarter-to-date for the quarter after the last complete one
    ny, nq = (y + 1, 1) if q == 4 else (y, q + 1)
    ns, _ = q_bounds(ny, nq)
    qtd = {"quarter": f"Q{nq} {ny}", "start": ns.isoformat(), "through": None, "days": 0,
           "complete_weeks": 0, "total": None, "prior_year_total": None, "yoy_pct": None, "shown": False}
    if last_day >= ns:
        days = (last_day - ns).days + 1
        cur_qtd = span_total(dm, ns, last_day)
        ly_start = date(ny - 1, ns.month, ns.day)
        ly_qtd = span_total(dm, ly_start, ly_start + timedelta(days=days - 1))
        qtd.update({"through": last_day.isoformat(), "days": days, "complete_weeks": days // 7,
                    "total": round(cur_qtd, 1) if cur_qtd is not None else None,
                    "prior_year_total": round(ly_qtd, 1) if ly_qtd is not None else None,
                    "yoy_pct": pct(cur_qtd, ly_qtd), "shown": days // 7 >= 4})
    return {
        "quarter": f"Q{q} {y}", "start": qs.isoformat(), "end": qe.isoformat(),
        "total": round(cur, 1) if cur is not None else None,
        "prior_year_total": round(ly, 1) if ly is not None else None,
        "prior_quarter": f"Q{pq} {py_}", "prior_quarter_total": round(prev, 1) if prev is not None else None,
        "yoy_pct": pct(cur, ly), "seq_pct": pct(cur, prev),
        "typical_seq_pct": typical, "typical_basis": seasonal,
        "prorated_weeks": boundary_weeks(rows, qs, qe),
        "qtd": qtd,
    }
