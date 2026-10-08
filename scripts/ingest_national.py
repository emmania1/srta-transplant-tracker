"""Parse OPTN national-data snapshots (scripts/fetch_optn_national.py) into
donor_mix / distance / location payloads.

These reports are annual: "<current year>" = Jan 1 through the snapshot's
period end (last full month); prior years are full years. So:
  * donor mix + distance are compared as SHARES: current year-to-date vs the
    prior full year. That is a mix comparison, not a like-for-like volume one.
  * when a snapshot from the same period end a year earlier exists, a true same-period
    comparison is added automatically (`same_period`). OPTN's report builder has no month or
    quarter dimension (checked 2026-10-08: only Transplant Year / Donation Year), so snapshots
    are the only route to like-for-like.
  * state volumes get no % change until a snapshot exists for the same period
    end one year earlier (true YTD vs YTD). Until then the page shows shares.
"""
import csv
import json
import re
from datetime import date
from pathlib import Path

SNAP = re.compile(r"_optn_national_(?P<query>[a-z_]+)_thru-(?P<end>\d{4}-\d{2}-\d{2})\.(csv|json)$")
ORGANS = ["heart", "liver", "lung", "kidney"]
GROUP = "Deceased Donor"
FIRST_YEAR = 2019
BANDS = [  # (OPTN label prefix, display label)
    ("0 to 150 Nautical Miles", "0–150"),
    ("151 to 200 Nautical Miles", "151–200"),
    ("201 to 250 Nautical Miles", "201–250"),
    ("251 to 500 Nautical Miles", "251–500"),
    ("500+ Nautical Miles", "500+"),
]
LONG_BANDS = ["251–500", "500+"]


def snapshots(national_dir):
    """{period_end: {"meta": dict, "files": {query: Path}}}; newest download per period wins."""
    snaps = {}
    for p in sorted(national_dir.glob("*_optn_national_*"), reverse=True):
        m = SNAP.search(p.name)
        if not m:
            continue
        s = snaps.setdefault(m["end"], {"meta": None, "files": {}})
        if m["query"] == "meta":
            s["meta"] = s["meta"] or json.loads(p.read_text())
        else:
            s["files"].setdefault(m["query"], p)
    return {k: v for k, v in snaps.items() if v["meta"]}


def table(path):
    """{row label: {column: value}} for the deceased-donor group."""
    out = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["group"] == GROUP:
                out.setdefault(r["row"], {})[r["column"]] = int(r["value"])
    return out


def pct(n, d):
    return round(100 * n / d, 1) if d else None


def period_info(meta):
    end = date.fromisoformat(meta["period_end"])
    return {
        "period_end": meta["period_end"], "data_as_of": meta["data_as_of"],
        "current_year": end.year, "prior_year": end.year - 1,
        "current_label": f"{end.year} YTD (Jan 1–{end.strftime('%b')} {end.day})",
        "prior_label": f"{end.year - 1} full year",
        "comparison_note": ("Mix comparison: shares of the current year to date vs. the prior full year. "
                            "OPTN national reports are annual-only, so this is not a same-period volume comparison."),
    }


def dcd_split(t, year):
    y = str(year)
    total = t.get("All DCD + non-DCD", {}).get(y, 0)
    dbd = t.get("Brain Death Donor", {}).get(y, 0)
    dcd = t.get("DCD Donor", {}).get(y, 0)
    return {"dbd": dbd, "dcd": dcd, "not_reported": total - dbd - dcd, "total": total,
            "dcd_share_pct": pct(dcd, total)}


def build_donor_mix(snap):
    info = period_info(snap["meta"])
    years = list(range(FIRST_YEAR, info["current_year"] + 1))
    files = snap["files"]
    out = {**info, "years": years,
           "donors": {str(y): dcd_split(table(files["donors_dcd"]), y) for y in years},
           "transplants_by_organ": {}}
    for o in ORGANS:
        t = table(files[f"tx_dcd_{o}"])
        out["transplants_by_organ"][o] = {str(y): dcd_split(t, y) for y in years}
    out["organ_definitions"] = {"kidney": "Kidney alone (kidney-pancreas is a separate OPTN organ category here)"}
    return out


def build_distance(snap):
    info = period_info(snap["meta"])
    years = list(range(FIRST_YEAR, info["current_year"] + 1))
    out = {**info, "years": years, "band_order": [b[1] for b in BANDS], "long_bands": LONG_BANDS,
           "units": "nautical miles, donor hospital to transplant center", "organs": {}}
    for o in ORGANS:
        t = table(snap["files"][f"tx_distance_{o}"])
        per_year = {}
        for y in map(str, years):
            bands = {disp: sum(v.get(y, 0) for k, v in t.items() if k.startswith(lab)) for lab, disp in BANDS}
            known = sum(bands.values())
            total = t.get("All Zones", {}).get(y, 0)
            per_year[y] = {
                "bands": bands, "total": total, "unknown": total - known,
                # shares over transplants with a known band; flagged if the bands don't cover the total
                "shares_pct": {b: pct(n, known) for b, n in bands.items()},
                "long_share_pct": pct(sum(bands[b] for b in LONG_BANDS), known),
                "bands_cover_total": known == total,
            }
        out["organs"][o] = per_year
    return out


def build_location(snaps):
    """State table: latest snapshot shares + monthly snapshot history for future YoY."""
    ends = sorted(snaps)
    latest = snaps[ends[-1]]
    info = period_info(latest["meta"])
    cy, py = str(info["current_year"]), str(info["prior_year"])
    t = table(latest["files"]["tx_state_all"])
    nat_cur = t.get("All Center States", {}).get(cy, 0)
    nat_pri = t.get("All Center States", {}).get(py, 0)

    history = []
    for e in ends:
        st = table(snaps[e]["files"]["tx_state_all"])
        y = str(date.fromisoformat(e).year)
        history.append({"period_end": e, "data_as_of": snaps[e]["meta"]["data_as_of"],
                        "ytd": {k: v.get(y, 0) for k, v in st.items() if k != "All Center States"},
                        "ytd_national": st.get("All Center States", {}).get(y, 0)})

    # True YoY only when a snapshot exists for the same period end one year earlier
    ly_end = year_ago(ends[-1])
    ly = next((h for h in history if h["period_end"] == ly_end), None)

    rows = []
    for state, v in t.items():
        if state == "All Center States":
            continue
        cur, pri = v.get(cy, 0), v.get(py, 0)
        if not cur and not pri:
            continue
        row = {"state": state, "ytd": cur, "prior_full_year": pri,
               "share_pct": pct(cur, nat_cur), "prior_share_pct": pct(pri, nat_pri)}
        if ly:
            ly_n = ly["ytd"].get(state)
            row["same_period_last_year"] = ly_n
            row["yoy_pct"] = round(100 * (cur / ly_n - 1), 1) if ly_n else None
        rows.append(row)
    rows.sort(key=lambda r: -r["ytd"])
    return {**info, "level": "state", "national_ytd": nat_cur, "national_prior_full_year": nat_pri,
            "rows": rows, "yoy_available": bool(ly), "yoy_basis_period_end": ly_end,
            "snapshots": history,
            "yoy_note": (f"True YoY appears once a snapshot through {ly_end} exists; snapshots are saved monthly from "
                         f"{ends[0]}." if not ly else f"YoY = YTD through {ends[-1]} vs YTD through {ly_end}."),
            "organ_scope": "All organs, deceased-donor transplants, by state of transplant center"}


CENTER_ORGANS = ["heart", "liver", "lung"]
TOP_N = 25


def center_table(path, col_filter=None):
    """{center: {column: value}} from an advanced-builder center query."""
    out = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if col_filter and r["column"] != col_filter:
                continue
            out.setdefault(r["row"], {})[r["column"]] = int(r["value"])
    return out


def build_centers(snap):
    info = period_info(snap["meta"])
    files = snap["files"]
    if not all(f"centers_{o}_years" in files and f"centers_{o}_ytd" in files for o in CENTER_ORGANS):
        return None
    cy, fy, py = info["current_year"], info["prior_year"], info["prior_year"] - 1
    centers = {}
    for o in CENTER_ORGANS:
        yrs = center_table(files[f"centers_{o}_years"])
        ytd = center_table(files[f"centers_{o}_ytd"], col_filter="All Regions")
        for c in set(yrs) | set(ytd):
            d = centers.setdefault(c, {"organs": {}})
            d["organs"][o] = {str(fy): yrs.get(c, {}).get(str(fy), 0), str(py): yrs.get(c, {}).get(str(py), 0),
                              f"{cy}_ytd": ytd.get(c, {}).get("All Regions", 0)}
    rows = []
    for c, d in centers.items():
        if c == "All Centers":
            continue
        tot = {k: sum(v[k] for v in d["organs"].values()) for k in (str(fy), str(py), f"{cy}_ytd")}
        code, _, name = c.partition(" ")
        rows.append({"center": name or c, "center_code": code, "organs": d["organs"],
                     "total_" + str(fy): tot[str(fy)], "total_" + str(py): tot[str(py)],
                     "total_ytd": tot[f"{cy}_ytd"],
                     "yoy_pct": round(100 * (tot[str(fy)] / tot[str(py)] - 1), 1) if tot[str(py)] else None})
    rows.sort(key=lambda r: -r["total_" + str(fy)])
    nat = centers.get("All Centers", {"organs": {}})["organs"]
    return {**info, "full_year": fy, "comparison_year": py, "top_n": TOP_N, "rows": rows[:TOP_N],
            "centers_with_volume": sum(1 for r in rows if r["total_" + str(fy)] > 0),
            "national": {o: v for o, v in nat.items()},
            "scope": "Deceased-donor heart + liver + lung transplants by transplant center (OPTN center code + name)",
            "yoy_note": (f"YoY = {fy} vs {py}, both full years (like-for-like). {cy} YTD is through "
                         f"{info['period_end']} and has no YoY until a snapshot from a year earlier exists."),
            "source_detail": "OPTN national data, Build advanced report: rows Transplant Center, Deceased Donor filter"}


def year_ago(end_iso):
    end = date.fromisoformat(end_iso)
    try:
        return end.replace(year=end.year - 1).isoformat()
    except ValueError:  # Feb 29
        return end.replace(year=end.year - 1, day=28).isoformat()


def same_period(snaps, latest_end, builder):
    """Like-for-like prior-year comparison from the snapshot saved a year earlier, if any."""
    ly_end = year_ago(latest_end)
    if ly_end not in snaps:
        return {"available": False, "needs_snapshot_through": ly_end,
                "note": f"Same-period comparison appears once a snapshot through {ly_end} exists "
                        f"(snapshots saved monthly since {min(snaps)})."}
    return {"available": True, "prior_period_end": ly_end, "prior": builder(snaps[ly_end])}


def build_all(national_dir):
    snaps = snapshots(national_dir)
    if not snaps:
        return {}
    latest_end = max(snaps)
    s = snaps[latest_end]
    used = sorted(p.name for p in s["files"].values())
    common = {"raw_file": ", ".join(used), "data_as_of": s["meta"]["data_as_of"],
              "snapshot_downloaded": s["meta"]["downloaded"], "parser": "optn_national_data"}
    return {
        "donor_mix": {**build_donor_mix(s), **common,
                      "same_period": same_period(snaps, latest_end, build_donor_mix),
                      "snapshots_saved": sorted(snaps)},
        "distance": {**build_distance(s), **common,
                     "same_period": same_period(snaps, latest_end, build_distance),
                     "snapshots_saved": sorted(snaps)},
        "location": {**build_location(snaps), **common},
        **({"centers": {**c, **common}} if (c := build_centers(s)) else {}),
    }
