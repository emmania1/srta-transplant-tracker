// SRTA Transplant Tracker — renders everything from data/*.json. No numbers live in this file.
const ORGANS = ["heart", "liver", "lung", "kidney"];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const fmtInt = (n) => (n == null ? "n/a" : Math.round(n).toLocaleString("en-US"));
// One date format everywhere: "Sep 30, 2026"
const fmtDate = (s) => {
  if (!s) return "n/a";
  const d = new Date(s.length <= 10 ? s + "T12:00:00Z" : s);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
};
const fmtMonth = (y, m) => new Date(Date.UTC(y, m - 1, 15)).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const pctTxt = (v) => (v == null ? "n/a" : `${v.toFixed(1)}%`);
const fmtUsd = (v) => (v == null ? "n/a" : `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const fmtUsdM = (v) => (v == null ? "n/a" : `$${(v / 1e6).toFixed(1)}M`);

function yoy(p) {
  if (p == null) return `<span class="flat">n/a</span>`;
  if (p > 0) return `<span class="up">▲ ${p.toFixed(1)}%</span>`;
  if (p < 0) return `<span class="down">▼ ${Math.abs(p).toFixed(1)}%</span>`;
  return `<span class="flat">— 0.0%</span>`;
}
// share and rate shifts: arrow + text, neutral colour (not good or bad by itself)
function ptsChange(v) {
  if (v == null) return `<span class="nowrap">n/a</span>`;
  return `<span class="nowrap">${v > 0 ? "▲" : v < 0 ? "▼" : "—"} ${Math.abs(v).toFixed(1)} pts</span>`;
}
const pts1 = (a, b) => (a != null && b != null ? Math.round(10 * (a - b)) / 10 : null);
function awaiting(what, src) {
  return `<div class="awaiting"><strong>Awaiting data.</strong> ${esc(what)} will appear once ${esc(src)} is loaded.</div>`;
}
// The one-line footer on every panel
function srcLine(id, { name, cadence, tag, through }) {
  const el = $(id);
  if (!el) return;
  el.innerHTML = `Source: ${esc(name)} · updated ${esc(cadence)} · <span class="tier-tag ${tag.toLowerCase()}">${esc(tag)}</span>`
    + (through ? ` · data through ${esc(through)}` : "");
}
async function load(path) {
  try {
    const r = await fetch(path, { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch (e) {
    return { status: "missing", _error: String(e) };
  }
}
function weekKey(r) {
  if (r.yr != null) return { year: r.yr, week: r.week }; // OPTN calendar-year weeks
  const d = new Date(r.week_start + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + 3);
  const day = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - day + 3);
  const year = d.getUTCFullYear();
  const jan4 = new Date(Date.UTC(year, 0, 4));
  return { year, week: 1 + Math.round(((d - jan4) / 864e5 - 3 + ((jan4.getUTCDay() + 6) % 7)) / 7) };
}
const lastWeekEnd = (series) => series.reduce((m, r) => (r.week_end > m ? r.week_end : m), "");

const OPTN_WEEKLY = "OPTN metrics dashboard";
const OPTN_NATIONAL = "OPTN national data reports";

// Kidney differs by source: the OPTN weekly dashboard's Kidney includes kidney-pancreas;
// OPTN national data's Kidney is kidney alone. Labels say which.
const KIDNEY_DASH = "Kidney (incl. kidney-pancreas)";
const KIDNEY_ALONE = "Kidney (alone)";
const dashLabel = (o) => (o === "kidney" ? KIDNEY_DASH : o === "all" ? "All organs" : cap(o));
const aloneLabel = (o) => (o === "kidney" ? KIDNEY_ALONE : cap(o));

// ---------- 1. Snapshot ----------
function renderHeader(summary, price) {
  const P = (summary.prices || {}).tickers || {};
  const box = (sym) => {
    const p = P[sym], v = $(`${sym.toLowerCase()}-val`), c = $(`${sym.toLowerCase()}-chg`);
    if (!p) { v.textContent = "—"; c.innerHTML = `<span class="flat">Awaiting data</span>`; return; }
    v.textContent = fmtUsd(p.close);
    c.innerHTML = `${yoy(p.change_1w_pct)} <span class="muted">1 week</span>`;
  };
  box("SRTA");
  box("TMDX");
  const failed = Object.entries(price.tickers || {}).filter(([, v]) => v.fetch_error).map(([k]) => k);
  srcLine("src-price", { name: "Yahoo Finance", cadence: "weekly", tag: "Live", through: P.SRTA ? fmtDate(P.SRTA.date) : null });
  if (failed.length) $("src-price").innerHTML += ` · last refresh failed for ${esc(failed.join(", "))}`;
  $("page-updated").textContent = summary.generated_at ? `Page last updated ${fmtDate(summary.generated_at)}` : "";
}

function renderHealth(h) {
  const issues = (h && h.issues) || [];
  const banner = $("health-banner");
  if (issues.length) {
    banner.hidden = false;
    banner.innerHTML = `<strong>⚠ Data issue${issues.length > 1 ? "s" : ""}.</strong> The page is showing the last good data.<ul>${issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
  }
  const notes = (h && h.notices) || [];
  const li = $("health-notices");
  if (notes.length) li.innerHTML = `<strong>Setup:</strong> ${esc(notes.join(" "))} Add the repository secret <code>SEC_USER_AGENT</code> with a contact email.`;
  else li.remove();
}

const LABEL_ARROW = { up: "▲", longer: "▲", rising: "▲", down: "▼", shorter: "▼", falling: "▼" };
function renderSignals(summary) {
  const sig = summary.signals;
  if (!sig) { $("signals-body").innerHTML = awaiting("Signal labels", "OPTN data"); return; }
  const num = (v, unit) => (v == null ? "n/a" : `${v > 0 ? "+" : ""}${v.toFixed(1)}${unit === "%" ? "%" : " pts"}`);
  const chip = (name, v) => `<span class="sig-chip"><span class="sig-name">${esc(name)}</span>
    <span class="sig-label">${LABEL_ARROW[v.label] || "—"} ${esc(v.label || "n/a")}</span> <span class="sig-num">${num(v.value, v.unit)}</span></span>`;
  const t = sig.thresholds;
  const mix = summary.donor_mix_and_distance;
  const mixBasis = mix ? `${mix.period_end.slice(0, 4)} YTD through ${fmtDate(mix.period_end)} vs. full-year ${Number(mix.period_end.slice(0, 4)) - 1}` : "";
  const disc = (summary.donors || {}).discard;
  let discBasis = "";
  if (disc && disc.through) {
    const dt = new Date(`${disc.through}, ${disc.year} 12:00 UTC`);
    discBasis = isNaN(dt) ? "" : `YTD through ${fmtDate(dt.toISOString().slice(0, 10))} vs. same period last year`;
  }
  const rows = [
    ["Transplant volumes", `last 4 weeks vs. last year · flat = within ±${t.volumes.flat_within_pct}% · kidney incl. kidney-pancreas`,
      ORGANS.map((o) => chip(cap(o), sig.volumes[o])).join("")],
    sig.distance ? ["Distance: 251+ NM share", `${esc(mixBasis)} · flat = within ±${t.distance.flat_within_pts} pt · kidney alone`,
      ORGANS.map((o) => chip(cap(o), sig.distance[o])).join("")] : null,
    sig.dcd_share ? ["DCD share of donors", `${esc(mixBasis)} · flat = within ±${t.dcd_share.flat_within_pts} pt`, chip("All donors", sig.dcd_share)] : null,
    sig.discard_rate ? ["Discard rate", `${esc(discBasis)} · flat = within ±${t.discard_rate.flat_within_pts} pt`, chip("All organs", sig.discard_rate)] : null,
  ].filter(Boolean);
  $("signals-body").innerHTML = rows.map(([h, basis, chips]) =>
    `<div class="sig-row"><div class="sig-head"><strong>${h}</strong><span class="muted">${basis}</span></div><div class="sig-chips">${chips}</div></div>`).join("");
}

// Plain-English "This week" sentences built from the same numbers as the chips
function joinList(xs) {
  return xs.length <= 1 ? xs.join("") : xs.length === 2 ? `${xs[0]} and ${xs[1]}` : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}
// items in display order: [{name, value, label: up|flat|down}] -> "Heart transplants fell 5.8% over …; liver and lung rose 6.8% and 5.4%."
function directionSentence(items, noun, period) {
  const order = [], groups = {};
  items.filter((i) => i.value != null).forEach((i) => {
    if (!groups[i.label]) { groups[i.label] = []; order.push(i.label); }
    groups[i.label].push(i);
  });
  if (!order.length) return null;
  const parts = order.map((k, idx) => {
    const g = groups[k];
    const names = joinList(g.map((i, j) => (idx === 0 && j === 0 ? i.name : i.name.toLowerCase())));
    const n = idx === 0 ? noun : "";
    const p = idx === 0 ? period : "";
    if (k === "flat") {
      return `${names}${n} ${g.length > 1 || n ? "were" : "was"} roughly flat${p} (${g.map((i) => `${i.value > 0 ? "+" : ""}${i.value.toFixed(1)}%`).join(", ")})`;
    }
    return `${names}${n} ${k === "up" ? "rose" : "fell"} ${joinList(g.map((i) => `${Math.abs(i.value).toFixed(1)}%`))}${p}`;
  });
  return parts.join("; ") + ".";
}
function renderThisWeek(summary) {
  const out = [];
  const sig = summary.signals || {};
  const optn = summary.optn || {};
  if (optn.status === "ok" && !optn.new_data_this_week) out.push("No new OPTN weekly data arrived this week, so transplant figures are unchanged.");
  if (sig.volumes) {
    const s = directionSentence(ORGANS.map((o) => ({ name: cap(o), value: sig.volumes[o].value, label: sig.volumes[o].label })),
      " transplants", " over the last 4 weeks vs. last year");
    if (s) out.push(s);
  }
  const d = summary.donors;
  if (d && d.metrics && d.metrics.trailing_4wk) {
    const v = d.metrics.trailing_4wk.yoy_pct;
    let s = `Deceased donors recovered ${v > 0 ? "rose" : v < 0 ? "fell" : "were flat at"} ${Math.abs(v).toFixed(1)}% over the same weeks`;
    if (d.discard) s += `, and ${d.discard.discard_rate_pct.toFixed(1)}% of recovered organs have been discarded so far this year (${d.discard.prior_year_discard_rate_pct.toFixed(1)}% a year earlier)`;
    out.push(s + ".");
  }
  const mix = summary.donor_mix_and_distance;
  if (mix && sig.distance) {
    const d0 = mix.dcd_share_donors;
    const longer = ORGANS.filter((o) => sig.distance[o].label === "longer");
    const shorter = ORGANS.filter((o) => sig.distance[o].label === "shorter");
    const dist = !longer.length && !shorter.length ? "the share of organs travelling 251+ NM held steady for every organ"
      : [longer.length ? `rose for ${joinList(longer)}` : "", shorter.length ? `fell for ${joinList(shorter)}` : ""]
        .filter(Boolean).join(" and ").replace(/^/, "the share of organs travelling 251+ NM ") + (longer.length + shorter.length < 4 ? " and held steady for the rest" : "");
    const priorYear = mix.prior_label.replace(" full year", "");
    out.push(`DCD donors are ${d0.current.toFixed(1)}% of deceased donors so far this year, up from ${(d0.current - d0.change_pts).toFixed(1)}% in ${priorYear}; ${dist}.`
      .replace("up from", d0.change_pts >= 0 ? "up from" : "down from"));
  }
  const wl = summary.waitlist;
  if (wl && out.length < 4) {
    const band = (sig.thresholds || {}).volumes?.flat_within_pct ?? 2;
    const s = directionSentence(ORGANS.map((o) => {
      const v = wl[o]?.trailing_4wk?.yoy_pct;
      return { name: cap(o), value: v, label: v == null ? "flat" : v > band ? "up" : v < -band ? "down" : "flat" };
    }), " waitlist additions", " over the last 4 weeks");
    if (s) out.push(s);
  }
  $("this-week-list").innerHTML = out.slice(0, 4).map((s) => `<li>${esc(s)}</li>`).join("") || "<li>Awaiting data.</li>";
  const heads = ((summary.news || {}).top_headlines || []).slice(0, 3);
  $("top-heads").innerHTML = heads.length ? heads.map((h) => `<li><a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.headline)}</a> <span class="muted">${esc(h.source)} · ${fmtDate(h.date)}</span></li>`).join("")
    : `<li class="muted">No qualifying headlines in the last 14 days.</li>`;
  const through = optn.all_organs?.latest_week?.week_end;
  srcLine("src-signals", { name: "OPTN, Google News", cadence: "weekly", tag: "Live", through: through ? fmtDate(through) : null });
}

// ---------- 2. Volumes ----------
function totalSeries(organs) {
  const maps = ORGANS.map((o) => new Map((organs[o] || []).map((r) => [r.week_start, r])));
  if (maps.some((m) => m.size === 0)) return [];
  return [...maps[0].keys()].filter((k) => maps.every((m) => m.has(k))).sort()
    .map((k) => ({ week_start: k, week_end: maps[0].get(k).week_end, count: maps.reduce((s, m) => s + m.get(k).count, 0) }));
}

function weeklyPanel({ id, data, metrics, what, src, unit, yTitle }) {
  let current = "heart", mode = "avg", chart = null;
  const ok = data.status === "ok";
  const cardsEl = $(`${id}-cards`), tabsEl = $(`${id}-tabs`), modeEl = $(`${id}-mode`);

  const cards = () => {
    cardsEl.innerHTML = ORGANS.map((o) => {
      const m = (metrics || {})[o];
      if (!ok || !m) {
        return `<button class="card awaiting-card" data-organ="${o}" aria-pressed="${o === current}">
          <div class="organ">${dashLabel(o)}</div><div class="kpi-label">Last 4 weeks vs. last year</div><div class="kpi">Awaiting data</div></button>`;
      }
      const t4 = m.trailing_4wk || {}, ytd = m.ytd || {}, w = m.latest_week || {};
      return `<button class="card" data-organ="${o}" aria-pressed="${o === current}">
        <div class="organ">${dashLabel(o)}</div>
        <div class="kpi-label">Last 4 weeks vs. last year</div>
        <div class="kpi">${yoy(t4.yoy_pct)}</div>
        <div class="sub">${fmtInt(t4.total)} vs. ${fmtInt(t4.prior_year_total)} ${unit}</div>
        <div class="sub">YTD ${yoy(ytd.yoy_pct)} (${fmtInt(ytd.total)} ${unit})</div>
        <div class="sub">Week ending ${fmtDate(w.week_end)}: ${fmtInt(w.count)} (${yoy(w.yoy_pct)})</div>
      </button>`;
    }).join("");
    cardsEl.querySelectorAll(".card").forEach((b) => b.addEventListener("click", () => select(b.dataset.organ)));
  };

  const draw = () => {
    const wrap = $(`${id}-chart-wrap`);
    if (!ok) {
      wrap.style.height = "auto";
      wrap.innerHTML = awaiting(what, src);
      $(`${id}-table`)?.closest(".table-view")?.setAttribute("hidden", "");
      return;
    }
    const organs = data.organs || {};
    const rows = (current === "all" ? (organs.all?.length ? organs.all : totalSeries(organs)) : organs[current] || [])
      .slice().sort((a, b) => (a.week_start < b.week_start ? -1 : 1));
    const raw = {}, avg = {};
    rows.forEach((r, i) => {
      const { year, week } = weekKey(r);
      (raw[year] = raw[year] || {})[week] = r.count;
      // 4-week rolling average over consecutive weeks (crosses year ends)
      (avg[year] = avg[year] || {})[week] = i >= 3 ? rows.slice(i - 3, i + 1).reduce((s, x) => s + x.count, 0) / 4 : null;
    });
    const vals = mode === "avg" ? avg : raw;
    const years = Object.keys(raw).map(Number).sort((a, b) => b - a).slice(0, 3);
    const colors = [css("--yr0"), css("--yr1"), css("--yr2")];
    const labels = Array.from({ length: 52 }, (_, i) => i + 1);
    const datasets = years.map((y, i) => ({
      label: String(y),
      data: labels.map((w) => vals[y][w] ?? null),
      borderColor: colors[i], backgroundColor: colors[i],
      borderWidth: i === 0 ? 3 : 1.25, pointRadius: 0, pointHoverRadius: 4, spanGaps: false, tension: 0.25,
      order: i === 0 ? 0 : 1,
    }));
    if (chart) chart.destroy();
    chart = new Chart($(`${id}-chart`), {
      type: "line", data: { labels, datasets },
      options: {
        maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "top", align: "end", labels: { color: css("--text-2"), boxWidth: 14, boxHeight: 2 } },
          tooltip: { callbacks: { title: (it) => `${dashLabel(current)} · week ${it[0].label}`, label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } },
        },
        scales: {
          x: { title: { display: true, text: "Week of year (week 1 starts Jan 1)", color: css("--muted") }, ticks: { color: css("--muted"), maxTicksLimit: 14 }, grid: { display: false } },
          y: { title: { display: true, text: `${yTitle}${mode === "avg" ? " (4-week avg.)" : ""}`, color: css("--muted") }, ticks: { color: css("--muted"), callback: (v) => fmtInt(v) }, grid: { color: css("--grid") } },
        },
      },
    });
    $(`${id}-table`).innerHTML = `<div class="scroll-x"><table><thead><tr><th>Week</th>${years.map((y) => `<th>${y}</th>`).join("")}</tr></thead><tbody>${
      labels.filter((w) => years.some((y) => raw[y][w] != null)).reverse()
        .map((w) => `<tr><td>Week ${w}</td>${years.map((y) => `<td>${fmtInt(raw[y][w] ?? null)}</td>`).join("")}</tr>`).join("")
    }</tbody></table></div>`;
  };

  const select = (o) => {
    current = o;
    cardsEl.querySelectorAll(".card").forEach((c) => c.setAttribute("aria-pressed", c.dataset.organ === o));
    tabsEl.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b.dataset.organ === o));
    draw();
  };

  cards();
  tabsEl.innerHTML = [...ORGANS, "all"].map((o) =>
    `<button role="tab" data-organ="${o}" aria-selected="${o === current}">${dashLabel(o)}</button>`).join("");
  tabsEl.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => select(b.dataset.organ)));
  modeEl.innerHTML = `<button data-m="avg" aria-pressed="true">4-week average</button><button data-m="raw" aria-pressed="false">Weekly</button>`;
  modeEl.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    mode = b.dataset.m;
    modeEl.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    draw();
  }));
  draw();
}

function renderVolumes(summary, tw) {
  weeklyPanel({ id: "vol", data: tw, metrics: (summary.optn || {}).organs, what: "Weekly transplant volumes", src: "the OPTN weekly download",
    unit: "transplants", yTitle: "Transplants per week" });
  const all = Object.values(tw.organs || {}).flat();
  srcLine("src-transplants", { name: OPTN_WEEKLY, cadence: "weekly", tag: "Live", through: all.length ? fmtDate(lastWeekEnd(all)) : null });
}

function renderWaitlist(summary, wl) {
  weeklyPanel({ id: "wl", data: wl, metrics: summary.waitlist, what: "Weekly waitlist additions", src: "the OPTN weekly waitlist download",
    unit: "additions", yTitle: "Additions per week" });
  const all = Object.values(wl.organs || {}).flat();
  srcLine("src-waitlist", { name: OPTN_WEEKLY, cadence: "weekly", tag: "Live", through: all.length ? fmtDate(lastWeekEnd(all)) : null });
}

function renderDonors(summary, dw) {
  const d = summary.donors;
  if (dw.status !== "ok" || !d || !d.metrics) { $("donor-body").innerHTML = awaiting("Deceased donors recovered", "the OPTN weekly download"); return; }
  const t4 = d.metrics.trailing_4wk || {}, ytd = d.metrics.ytd || {}, w = d.metrics.latest_week || {};
  const disc = d.discard;
  $("donor-body").innerHTML = `<div class="stat-row">
    <div class="stat"><div class="kpi-label">Donors, last 4 weeks vs. last year</div><div class="kpi">${yoy(t4.yoy_pct)}</div>
      <div class="sub">${fmtInt(t4.total)} vs. ${fmtInt(t4.prior_year_total)} donors</div></div>
    <div class="stat"><div class="kpi-label">Donors, year to date vs. last year</div><div class="kpi">${yoy(ytd.yoy_pct)}</div>
      <div class="sub">${fmtInt(ytd.total)} donors</div></div>
    <div class="stat"><div class="kpi-label">Week ending ${fmtDate(w.week_end)}</div><div class="kpi">${fmtInt(w.count)} <span class="kpi-unit">donors</span></div>
      <div class="sub">${yoy(w.yoy_pct)} vs. same week last year</div></div>
    ${disc ? `<div class="stat"><div class="kpi-label">Discard rate, year to date</div><div class="kpi neutral">${disc.discard_rate_pct.toFixed(1)}%</div>
      <div class="sub">${disc.prior_year_discard_rate_pct.toFixed(1)}% a year earlier · ${ptsChange(disc.change_pts)}</div></div>` : ""}
  </div>`;
  let discThrough = null;
  if (disc && disc.through) {
    const dt = new Date(`${disc.through}, ${disc.year} 12:00 UTC`);
    if (!isNaN(dt)) discThrough = fmtDate(dt.toISOString().slice(0, 10));
  }
  srcLine("src-donors", { name: OPTN_WEEKLY, cadence: "weekly", tag: "Live",
    through: discThrough ? `${fmtDate(w.week_end)} (donors), ${discThrough} (discard rate)` : fmtDate(w.week_end) });
}

// ---------- 3. Donor mix ----------
const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5"];
let mixChart = null;
function renderDonorMix(d) {
  if (d.status !== "ok") { $("mix-body").innerHTML = awaiting("DBD vs. DCD shares", "the OPTN national data"); return; }
  const cy = String(d.current_year), py = String(d.prior_year);
  const rows = [["All deceased donors", d.donors], ...ORGANS.map((o) => [`${aloneLabel(o)} transplants`, d.transplants_by_organ[o]])];
  const tbl = rows.map(([name, v]) => {
    const c = v[cy], p = v[py];
    return `<tr><td>${esc(name)}</td><td>${fmtInt(c.dcd)} / ${fmtInt(c.total)}</td><td><strong>${pctTxt(c.dcd_share_pct)}</strong></td><td>${pctTxt(p.dcd_share_pct)}</td><td>${ptsChange(pts1(c.dcd_share_pct, p.dcd_share_pct))}</td></tr>`;
  }).join("");
  $("mix-body").innerHTML = `
    <p class="note">DCD share of the total, ${cy} year to date vs. full-year ${py}. OPTN's national reports are annual, so this compares mix, not volumes.</p>
    <div class="scroll-x"><table class="mix-table">
      <thead><tr><th></th><th>DCD / total (${cy} YTD)</th><th>${cy} YTD</th><th>${py}</th><th>Change</th></tr></thead>
      <tbody>${tbl}</tbody></table></div>
    <h4 class="sub-head">DCD share by year</h4>
    <div class="chart-wrap short"><canvas id="mix-chart" aria-label="DCD share by year"></canvas></div>`;
  const years = d.years.map(String);
  const datasets = rows.map(([name, v], i) => ({
    label: name.replace(" transplants", ""),
    data: years.map((y) => v[y]?.dcd_share_pct ?? null),
    borderColor: css(SERIES[i]), backgroundColor: css(SERIES[i]),
    borderWidth: i === 0 ? 3 : 1.75, pointRadius: years.map((y) => (y === cy ? 4 : 2)), tension: 0,
  }));
  if (mixChart) mixChart.destroy();
  mixChart = new Chart($("mix-chart"), {
    type: "line",
    data: { labels: years.map((y) => (y === cy ? `${y} YTD` : y)), datasets },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "top", align: "end", labels: { color: css("--text-2"), boxWidth: 12, boxHeight: 2 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${pctTxt(c.parsed.y)}` } },
      },
      scales: {
        x: { title: { display: true, text: "Year", color: css("--muted") }, ticks: { color: css("--muted") }, grid: { display: false } },
        y: { title: { display: true, text: "DCD share (%)", color: css("--muted") }, ticks: { color: css("--muted"), callback: (v) => v + "%" }, grid: { color: css("--grid") } },
      },
    },
  });
  srcLine("src-mix", { name: OPTN_NATIONAL, cadence: "monthly", tag: "Live", through: fmtDate(d.period_end) });
}

// ---------- 4. Distance & location ----------
const BAND_GROUPS = [
  { label: "0–150 NM", bands: ["0–150"], color: "--band-g1" },
  { label: "151–250 NM", bands: ["151–200", "201–250"], color: "--band-g2" },
  { label: "251+ NM", bands: ["251–500", "500+"], color: "--band-g3" },
];
let distChart = null;
function renderDistance(d) {
  if (d.status !== "ok") { $("dist-body").innerHTML = awaiting("Distance-band shares", "the OPTN national data"); return; }
  const cy = String(d.current_year), py = String(d.prior_year);
  const bands = d.band_order;
  const tbl = ORGANS.map((o) => {
    const c = d.organs[o][cy], p = d.organs[o][py];
    const cells = (x) => bands.map((b) => `<td>${pctTxt(x.shares_pct[b])}</td>`).join("");
    return `<tr><td rowspan="2"><strong>${aloneLabel(o)}</strong></td><td>${cy} YTD</td>${cells(c)}<td rowspan="2"><strong>${pctTxt(c.long_share_pct)}</strong> vs. ${pctTxt(p.long_share_pct)}<br>${ptsChange(pts1(c.long_share_pct, p.long_share_pct))}</td></tr>
            <tr class="prior"><td>${py}</td>${cells(p)}</tr>`;
  }).join("");
  $("dist-body").innerHTML = `
    <p class="note">Share of deceased-donor transplants by distance from donor hospital to transplant center, ${cy} year to date vs. full-year ${py}. The label on each bar is the 251+ NM share.</p>
    <div class="chart-wrap tall"><canvas id="dist-chart" aria-label="Distance band shares by organ"></canvas></div>
    <details class="table-view"><summary>Show all 5 distance bands as a table</summary><div class="scroll-x"><table class="dist-table">
      <thead><tr><th>Organ</th><th>Period</th>${bands.map((b) => `<th>${esc(b)} NM</th>`).join("")}<th>251+ NM</th></tr></thead>
      <tbody>${tbl}</tbody></table></div></details>`;
  const labels = ORGANS.flatMap((o) => [`${aloneLabel(o)} ${py}`, `${aloneLabel(o)} ${cy} YTD`]);
  const val = (o, y, g) => g.bands.reduce((s, b) => s + (d.organs[o][y].shares_pct[b] || 0), 0);
  const datasets = BAND_GROUPS.map((g) => ({
    label: g.label,
    data: ORGANS.flatMap((o) => [val(o, py, g), val(o, cy, g)]),
    backgroundColor: css(g.color), borderColor: css("--panel"), borderWidth: 1, borderSkipped: false,
  }));
  const longShares = ORGANS.flatMap((o) => [d.organs[o][py].long_share_pct, d.organs[o][cy].long_share_pct]);
  const longLabel = {
    id: "longLabel",
    afterDatasetsDraw(chart) {
      const { ctx } = chart, meta = chart.getDatasetMeta(2);
      ctx.save();
      ctx.font = "600 11px -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillStyle = css("--band-g3-ink");
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      meta.data.forEach((bar, i) => {
        const v = longShares[i]; // the file's own 251+ share (not a sum of rounded bands)
        if (Math.abs(bar.x - bar.base) > 30) ctx.fillText(`${v.toFixed(1)}%`, (bar.x + bar.base) / 2, bar.y);
      });
      ctx.restore();
    },
  };
  if (distChart) distChart.destroy();
  distChart = new Chart($("dist-chart"), {
    type: "bar", data: { labels, datasets }, plugins: [longLabel],
    options: {
      indexAxis: "y", maintainAspectRatio: false,
      plugins: {
        legend: { position: "top", align: "start", labels: { color: css("--text-2"), boxWidth: 12 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${pctTxt(c.parsed.x)}` } },
      },
      scales: {
        x: { stacked: true, max: 100, title: { display: true, text: "Share of transplants (%)", color: css("--muted") }, ticks: { color: css("--muted"), callback: (v) => v + "%" }, grid: { color: css("--grid") } },
        y: { stacked: true, title: { display: true, text: "Organ and period", color: css("--muted") }, ticks: { color: css("--text-2"), font: { size: 11 } }, grid: { display: false } },
      },
    },
  });
  srcLine("src-distance", { name: OPTN_NATIONAL, cadence: "monthly", tag: "Live", through: fmtDate(d.period_end) });
}

const STATE_ABBR = { Alabama: "AL", Alaska: "AK", Arizona: "AZ", Arkansas: "AR", California: "CA", Colorado: "CO", Connecticut: "CT", Delaware: "DE",
  "District of Columbia": "DC", Florida: "FL", Georgia: "GA", Hawaii: "HI", Idaho: "ID", Illinois: "IL", Indiana: "IN", Iowa: "IA", Kansas: "KS",
  Kentucky: "KY", Louisiana: "LA", Maine: "ME", Maryland: "MD", Massachusetts: "MA", Michigan: "MI", Minnesota: "MN", Mississippi: "MS", Missouri: "MO",
  Montana: "MT", Nebraska: "NE", Nevada: "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
  "North Dakota": "ND", Ohio: "OH", Oklahoma: "OK", Oregon: "OR", Pennsylvania: "PA", "Puerto Rico": "PR", "Rhode Island": "RI", "South Carolina": "SC",
  "South Dakota": "SD", Tennessee: "TN", Texas: "TX", Utah: "UT", Vermont: "VT", Virginia: "VA", Washington: "WA", "West Virginia": "WV",
  Wisconsin: "WI", Wyoming: "WY" };
const abbr = (s) => {
  const m = s.match(/^(Eastern|Western|Southern|Northern) (.+)$/);
  return m ? `${m[1].toLowerCase()} ${STATE_ABBR[m[2]] || m[2]}` : STATE_ABBR[s] || s;
};
function renderRegions(summary, rw) {
  const reg = (summary.regions || {}).regions;
  if (rw.status !== "ok" || !reg) { $("reg-body").innerHTML = awaiting("Weekly transplants by OPTN region", "the OPTN weekly region download"); return; }
  const states = rw.region_states || {}, names = rw.region_names || {};
  const rows = Object.entries(reg).filter(([, m]) => m).sort((a, b) => (b[1].trailing_4wk?.total ?? 0) - (a[1].trailing_4wk?.total ?? 0));
  const lw = rows[0]?.[1]?.latest_week;
  $("reg-body").innerHTML = `<p class="note">Deceased-donor transplants, all organs, by region of transplant center; sorted by the last 4 weeks.</p>
    <div class="scroll-x"><table class="reg-table">
    <thead><tr><th>Region</th><th>Last 4 weeks</th><th>Same weeks last year</th><th>Change</th><th>YTD change</th><th>Week ending ${fmtDate(lw?.week_end)}</th></tr></thead>
    <tbody>${rows.map(([r, m]) => `<tr>
      <td><strong>Region ${esc(r)} · ${esc(names[r] || "")}</strong> <span class="cell-sub">(${esc((states[r] || []).map(abbr).join(", "))})</span></td>
      <td>${fmtInt(m.trailing_4wk?.total)}</td><td>${fmtInt(m.trailing_4wk?.prior_year_total)}</td>
      <td>${yoy(m.trailing_4wk?.yoy_pct)}</td><td>${yoy(m.ytd?.yoy_pct)}</td>
      <td>${fmtInt(m.latest_week?.count)} (${yoy(m.latest_week?.yoy_pct)})</td></tr>`).join("")}</tbody></table></div>`;
  srcLine("src-regions", { name: `${OPTN_WEEKLY}; region membership per OPTN`, cadence: "weekly", tag: "Live", through: fmtDate(lw?.week_end) });
}

function renderLocation(d) {
  if (d.status !== "ok") { $("loc-body").innerHTML = awaiting("Transplants by state", "the OPTN national data"); return; }
  const cy = String(d.current_year), py = String(d.prior_year);
  $("loc-note").innerHTML = `Deceased-donor transplants, all organs, by state of transplant center: ${cy} year to date vs. full-year ${py}. `
    + (d.yoy_available ? "" : `Shares only for now: the state data is annual, so a % change would compare part of a year with a full year. A true year-over-year column appears once a snapshot from a year earlier exists (saved monthly since ${fmtDate(d.snapshots[0].period_end)}).`);
  let shown = 15;
  const draw = () => {
    $("loc-body").innerHTML = `<div class="scroll-x"><table>
      <thead><tr><th>State</th><th>${cy} YTD</th><th>Share</th><th>${py}</th><th>Share</th><th>Change in share</th>${d.yoy_available ? "<th>YoY (same period)</th>" : ""}</tr></thead>
      <tbody>${d.rows.slice(0, shown).map((r) => `<tr><td>${esc(r.state)}</td><td>${fmtInt(r.ytd)}</td><td><strong>${pctTxt(r.share_pct)}</strong></td><td>${fmtInt(r.prior_full_year)}</td><td>${pctTxt(r.prior_share_pct)}</td>
        <td>${ptsChange(pts1(r.share_pct, r.prior_share_pct))}</td>${d.yoy_available ? `<td>${yoy(r.yoy_pct)}</td>` : ""}</tr>`).join("")}
      <tr class="total"><td>U.S. total</td><td>${fmtInt(d.national_ytd)}</td><td>100%</td><td>${fmtInt(d.national_prior_full_year)}</td><td>100%</td><td></td>${d.yoy_available ? "<td></td>" : ""}</tr>
      </tbody></table></div>
      ${d.rows.length > shown ? `<button class="more" id="loc-more">Show all ${d.rows.length} states</button>` : ""}`;
    const more = $("loc-more");
    if (more) more.onclick = () => { shown = d.rows.length; draw(); };
  };
  draw();
  srcLine("src-states", { name: OPTN_NATIONAL, cadence: "monthly", tag: "Live", through: fmtDate(d.period_end) });
}

function renderCenters(d) {
  if (d.status !== "ok") { $("ctr-body").innerHTML = awaiting("Transplant center volumes", "the OPTN national data"); return; }
  const fy = d.full_year, py = d.comparison_year;
  $("ctr-note").textContent = `Deceased-donor heart, liver and lung transplants by center, ranked by ${fy}. The change compares two full years (${fy} vs. ${py}); ${d.current_year} year to date has no change column yet.`;
  let shown = 10;
  const draw = () => {
    $("ctr-body").innerHTML = `<div class="scroll-x"><table class="ctr-table">
      <thead><tr><th>#</th><th>Center</th><th>${fy}</th><th>${py}</th><th>Change</th><th>Heart / liver / lung, ${fy}</th><th>${d.current_year} YTD</th></tr></thead>
      <tbody>${d.rows.slice(0, shown).map((r, i) => `<tr><td>${i + 1}</td><td><strong>${esc(r.center)}</strong><div class="cell-sub">${esc(r.center_code)}</div></td>
        <td>${fmtInt(r["total_" + fy])}</td><td>${fmtInt(r["total_" + py])}</td><td>${yoy(r.yoy_pct)}</td>
        <td>${["heart", "liver", "lung"].map((o) => fmtInt(r.organs[o]?.[String(fy)] ?? 0)).join(" / ")}</td>
        <td>${fmtInt(r.total_ytd)}</td></tr>`).join("")}</tbody></table></div>
      ${d.rows.length > shown ? `<button class="more" id="ctr-more">Show all ${d.rows.length}</button>` : ""}`;
    const more = $("ctr-more");
    if (more) more.onclick = () => { shown = d.rows.length; draw(); };
  };
  draw();
  srcLine("src-centers", { name: `${OPTN_NATIONAL} (advanced report)`, cadence: "monthly", tag: "Live", through: fmtDate(d.period_end) });
}

// ---------- 5. Leading indicators ----------
let cdcChart = null;
function renderCdc(d) {
  if (d.status !== "ok") { $("cdc-body").innerHTML = awaiting("12-month overdose deaths", "the CDC dataset"); return; }
  const s = d.series.filter((x) => x.year >= d.series[d.series.length - 1].year - 5);
  const last = d.series[d.series.length - 1];
  $("cdc-body").innerHTML = `
    <div class="stat-row">
      <div class="stat"><div class="kpi-label">12 months ending ${fmtMonth(last.year, last.month)}, CDC estimate</div><div class="kpi">${fmtInt(last.predicted)} <span class="kpi-unit">deaths</span></div>
        <div class="sub">${yoy(last.predicted_yoy_pct)} vs. a year earlier</div></div>
      <div class="stat"><div class="kpi-label">Reported so far</div><div class="kpi">${fmtInt(last.reported)} <span class="kpi-unit">deaths</span></div>
        <div class="sub">${yoy(last.reported_yoy_pct)} vs. a year earlier</div></div>
    </div>
    <div class="chart-wrap short"><canvas id="cdc-chart" aria-label="12-month rolling overdose deaths"></canvas></div>
    <p class="note">The CDC estimate adjusts for deaths not yet reported; recent months are provisional. Fewer overdose deaths can mean fewer potential brain-death donors later. Context, not a forecast.</p>`;
  if (cdcChart) cdcChart.destroy();
  cdcChart = new Chart($("cdc-chart"), {
    type: "line",
    data: { labels: s.map((x) => fmtMonth(x.year, x.month)), datasets: [
      { label: "CDC estimate", data: s.map((x) => x.predicted), borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 3, pointRadius: 0 },
      { label: "Reported so far", data: s.map((x) => x.reported), borderColor: css("--yr2"), backgroundColor: css("--yr2"), borderWidth: 1.5, pointRadius: 0, borderDash: [4, 3] },
    ] },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top", align: "end", labels: { color: css("--text-2"), boxWidth: 14, boxHeight: 2 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } } },
      scales: { x: { title: { display: true, text: "12 months ending", color: css("--muted") }, ticks: { color: css("--muted"), maxTicksLimit: 8 }, grid: { display: false } },
        y: { title: { display: true, text: "Deaths (12-month total)", color: css("--muted") }, ticks: { color: css("--muted"), callback: (v) => fmtInt(v) }, grid: { color: css("--grid") } } } },
  });
  srcLine("src-cdc", { name: "CDC/NCHS provisional drug overdose death counts", cadence: "monthly", tag: "Live", through: fmtMonth(last.year, last.month) });
}

// ---------- 6. Company ----------
function fmtKpi(v, unit) {
  if (v == null) return `<span class="awaiting-inline">awaiting data</span>`;
  if (unit === "$M") return `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
  if (unit === "%") return `${Number(v).toFixed(1)}%`;
  return fmtInt(Number(v));
}
function lastCompletedQuarter(today = new Date()) {
  const q = Math.floor(today.getUTCMonth() / 3); // current quarter index 0..3
  return q === 0 ? `Q4 ${today.getUTCFullYear() - 1}` : `Q${q} ${today.getUTCFullYear()}`;
}
function renderKpis(d, bodyId, srcId, name) {
  if (!d.fields) { $(bodyId).innerHTML = awaiting("KPIs", "the quarterly KPI file"); return; }
  const periods = d.periods || [];
  const last = periods[periods.length - 1];
  const groups = [...new Set(d.fields.map((f) => f.group))];
  const table = `<div class="scroll-x"><table class="kpi-table"><thead><tr><th>Metric</th><th>${last ? esc(last.period) : "Latest quarter"}</th><th>Source</th><th>Date</th></tr></thead><tbody>
    ${groups.map((g) => `<tr class="grp"><td colspan="4">${esc(g)}</td></tr>` + d.fields.filter((f) => f.group === g).map((f) => {
      const v = last ? (last.values || {})[f.key] || {} : {};
      return `<tr><td>${esc(f.label)}</td><td>${fmtKpi(v.value, f.unit)}</td><td class="src-cell">${esc(v.source || "—")}</td><td>${v.date ? fmtDate(v.date) : "—"}</td></tr>`;
    }).join("")).join("")}</tbody></table></div>`;
  $(bodyId).innerHTML = periods.length ? table
    : `<p class="awaiting-line">Awaiting ${lastCompletedQuarter()} results — filled in after each earnings report.</p>
       <details class="table-view"><summary>Show the fields that will be tracked</summary>${table}</details>`;
  srcLine(srcId, { name, cadence: "quarterly", tag: "Manual", through: last ? `${last.period} (reported ${fmtDate(last.reported)})` : null });
}

function renderJoby(summary) {
  const j = (summary.prices || {}).joby;
  const p = ((summary.prices || {}).tickers || {}).JOBY;
  if (!j || !p) { $("joby-body").innerHTML = awaiting("JOBY earn-out value", "JOBY prices"); return; }
  $("joby-body").innerHTML = `<div class="stat-row">
    <div class="stat"><div class="kpi-label">Value at the latest JOBY price</div><div class="kpi">${fmtUsdM(j.value)}</div>
      <div class="sub">${(j.shares / 1e6).toFixed(2)}M shares (PM estimate) × ${fmtUsd(p.close)} · ${yoy(j.change_1w_pct)} 1 week</div></div>
    <div class="stat"><div class="kpi-label">Cap per SRTA's 10-Q</div><div class="kpi neutral">${fmtUsdM(j.cap_contingent_usd)} max</div>
      <div class="sub">contingent consideration, plus up to ${fmtUsdM(j.cap_holdback_usd)} indemnity holdback</div></div>
  </div>
  <p class="note">The 2.42M share count is a PM estimate, not a disclosed holding. SRTA's Q2 2026 10-Q says the 5,325,585 JOBY shares received at closing were sold; the remaining consideration is contingent and payable in cash or JOBY shares at Joby's election. <a href="${esc(j.source_url)}" target="_blank" rel="noopener">10-Q ↗</a></p>`;
  srcLine("src-joby", { name: "Yahoo Finance (JOBY price); SRTA 10-Q (cap); PM estimate (share count)", cadence: "weekly", tag: "Manual", through: fmtDate(p.date) });
}

// Filing types in plain words
const FORM_DESC = {
  "10-Q": "Quarterly report", "10-K": "Annual report", "8-K": "Material event report", "DEF 14A": "Proxy statement",
  "SCHEDULE 13D": "Large-holder ownership filing (active)", "SC 13D": "Large-holder ownership filing (active)",
  "SCHEDULE 13G": "Large-holder ownership filing (passive)", "SC 13G": "Large-holder ownership filing (passive)",
};
const ITEM_DESC = { "1.01": "material agreement", "2.01": "acquisition or disposal", "2.02": "results of operations", "2.03": "new obligation",
  "3.02": "unregistered share sale", "5.02": "officer or director change", "5.03": "charter or bylaw change", "5.07": "shareholder vote",
  "7.01": "Reg FD disclosure", "8.01": "other events", "9.01": "exhibits" };
function formDesc(f) {
  const base = f.form.replace("/A", "");
  let s = FORM_DESC[base] || f.description || f.form;
  if (f.form.endsWith("/A")) s += ", amendment";
  if (base === "8-K" && f.items) s += `: ${f.items.split(",").map((i) => ITEM_DESC[i.trim()] || `item ${i.trim()}`).join(", ")}`;
  return s;
}

// Form 4 in plain words
const F4_VERB = {
  A: (n) => `received ${n} shares (award)`, F: (n) => `${n} withheld for taxes`, S: (n) => `sold ${n} shares on the open market`,
  P: (n) => `bought ${n} shares`, M: (n) => `exercised options for ${n} shares`, G: (n) => `gave ${n} shares as a gift`,
  D: (n) => `returned ${n} shares to the company`, C: (n) => `converted ${n} shares`,
};
function f4Who(f4) {
  const last = (f4.owner || "").split(/[ ,]+/)[0];
  const name = last ? last.charAt(0) + last.slice(1).toLowerCase() : "Insider";
  const roles = f4.roles || [];
  const role = (roles.find((r) => r !== "Director" && r !== "10% owner") || roles[0] || "insider").replace(/ and /g, "/");
  return `${name} (${role})`;
}
function f4Text(f4, codes) {
  const by = {};
  (f4.transactions || []).filter((t) => !codes || codes.includes(t.code)).forEach((t) => {
    const k = t.code || "?";
    by[k] = by[k] || { n: 0, px: 0, pxn: 0 };
    by[k].n += t.shares || 0;
    if (t.price) { by[k].px += t.price * (t.shares || 0); by[k].pxn += t.shares || 0; }
  });
  const parts = Object.entries(by).map(([k, v]) => {
    let s = (F4_VERB[k] || ((x) => `code ${k}: ${x} shares`))(fmtInt(v.n));
    if (k === "S" && v.pxn) s += ` at about ${fmtUsd(v.px / v.pxn)}`;
    return s;
  });
  return `${f4Who(f4)}: ${parts.join(", ") || "no share transactions reported"}`;
}
function renderSec(d) {
  const filings = d.filings || [];
  if (!filings.length) {
    $("sec-body").innerHTML = awaiting("SRTA SEC filings", d.status === "not_configured" ? "the SEC contact setting is added (see About)" : "the SEC EDGAR fetch");
    return;
  }
  const sales = filings.filter((f) => f.form4?.open_market_sale);
  const d13 = filings.filter((f) => /13D/.test(f.form));
  const acts = [...sales.map((f) => ({ date: f.filed, text: f4Text(f.form4, ["S"]), url: f.url, kind: "Form 4" })),
    ...d13.map((f) => ({ date: f.filed, text: `${f.form}: ${formDesc(f).toLowerCase()}`, url: f.url, kind: "13D" }))]
    .sort((a, b) => (a.date < b.date ? 1 : -1));
  $("insider-strip").innerHTML = acts.length ? `<div class="insider"><div class="insider-head"><strong>Insider activity</strong> <span class="muted">open-market sales and 13D filings, last ${d.days || 180} days</span></div>
    <ul>${acts.map((a) => `<li><span class="nowrap">${fmtDate(a.date)}</span> · ${esc(a.text)} <a href="${esc(a.url)}" target="_blank" rel="noopener">${a.kind} ↗</a></li>`).join("")}</ul></div>` : "";
  const kind = (f) => (f.form.startsWith("4") ? "Form 4" : /13[DG]/.test(f.form) ? "13D / 13G" : f.form.replace("/A", ""));
  const kinds = [...new Set(filings.map(kind))];
  let filter = "all", shown = 10;
  const draw = () => {
    const rows = filings.filter((f) => filter === "all" || kind(f) === filter);
    $("sec-body").innerHTML = `<div class="scroll-x"><table class="sec-table"><thead><tr><th>Filed</th><th>Form</th><th>What it says</th><th></th></tr></thead><tbody>${
      rows.slice(0, shown).map((f) => {
        let desc = f.form4 ? esc(f4Text(f.form4)) : esc(formDesc(f));
        if (f.form4?.open_market_sale) desc += ` <span class="flag">open-market sale</span>`;
        if (/13D/.test(f.form)) desc += ` <span class="flag">13D</span>`;
        return `<tr><td class="nowrap">${fmtDate(f.filed)}</td><td class="nowrap">${esc(f.form)}</td><td class="desc">${desc}</td><td><a href="${esc(f.url)}" target="_blank" rel="noopener">Filing ↗</a></td></tr>`;
      }).join("")}</tbody></table></div>
      ${rows.length > shown ? `<button class="more" id="sec-more">Show all ${rows.length}</button>` : ""}`;
    const more = $("sec-more");
    if (more) more.onclick = () => { shown = rows.length; draw(); };
  };
  $("sec-filters").innerHTML = ["all", ...kinds].map((k) => `<button data-k="${esc(k)}" aria-pressed="${k === "all"}">${k === "all" ? "All" : esc(k)} (${k === "all" ? filings.length : filings.filter((f) => kind(f) === k).length})</button>`).join("");
  $("sec-filters").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.k; shown = 10;
    $("sec-filters").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    draw();
  }));
  draw();
  srcLine("src-sec", { name: "SEC EDGAR", cadence: "weekly", tag: "Live", through: fmtDate(d.fetched_at) });
  if (d.config_note) $("src-sec").innerHTML += " · not refreshing until the SEC contact setting is added (see About)";
}

let relChart = null;
function renderRelative(summary) {
  const r = (summary.prices || {}).relative_3m;
  if (!r) { $("rel-note").textContent = "Awaiting prices."; return; }
  $("rel-note").textContent = `Both indexed to 100 on ${fmtDate(r.base_date)}. SRTA is ${Math.abs(r.srta_minus_tmdx_pts).toFixed(1)} points ${r.srta_minus_tmdx_pts >= 0 ? "ahead of" : "behind"} TMDX over the period.`;
  if (relChart) relChart.destroy();
  relChart = new Chart($("rel-chart"), {
    type: "line",
    data: { labels: r.dates.map((d) => fmtDate(d).replace(/, \d{4}$/, "")), datasets: [
      { label: "SRTA", data: r.SRTA, borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 3, pointRadius: 0 },
      { label: "TMDX", data: r.TMDX, borderColor: css("--s2"), backgroundColor: css("--s2"), borderWidth: 1.75, pointRadius: 0 },
    ] },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top", align: "end", labels: { color: css("--text-2"), boxWidth: 14, boxHeight: 2 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}` } } },
      scales: { x: { title: { display: true, text: "Date", color: css("--muted") }, ticks: { color: css("--muted"), maxTicksLimit: 7 }, grid: { display: false } },
        y: { title: { display: true, text: "Index (start = 100)", color: css("--muted") }, ticks: { color: css("--muted") }, grid: { color: css("--grid") } } } },
  });
  srcLine("src-rel", { name: "Yahoo Finance", cadence: "weekly", tag: "Live", through: fmtDate(r.dates[r.dates.length - 1]) });
}

// ---------- News ----------
const NEWS_PAGE = 10;
function newsItem(i, labels) {
  return `<li>
    <a href="${esc(i.publisher_url || i.url)}" target="_blank" rel="noopener">${esc(i.headline)}</a>
    <div class="news-meta">${esc(i.source)} · ${fmtDate(i.date)} ${i.tags.map((t) => `<span class="chip">${esc(labels[t] || t)}</span>`).join("")}</div>
  </li>`;
}
function renderNews(news) {
  const items = news.items || [];
  const groups = news.groups || [];
  const labels = Object.fromEntries(groups.map((g) => [g.id, g.label]));
  const collapsedIds = new Set(groups.filter((g) => g.collapsed).map((g) => g.id));
  const isCollapsed = (i) => i.tags.length && i.tags.every((t) => collapsedIds.has(t));
  let filter = "all", shown = NEWS_PAGE;
  const filters = $("news-filters");
  filters.innerHTML = [{ id: "all", label: "All" }, ...groups].map((g) => {
    const n = g.id === "all" ? items.length : items.filter((i) => i.tags.includes(g.id)).length;
    return `<button data-f="${g.id}" aria-pressed="${g.id === "all"}">${esc(g.label)} (${n})</button>`;
  }).join("");
  const draw = () => {
    const main = filter === "all" ? items.filter((i) => !isCollapsed(i)) : items.filter((i) => i.tags.includes(filter));
    $("news-list").innerHTML = main.length ? main.slice(0, shown).map((i) => newsItem(i, labels)).join("")
      : `<li class="awaiting">No items in this category in the last ${news.lookback_days || 90} days.</li>`;
    $("news-more").hidden = main.length <= shown;
    $("news-more").textContent = `Show more (${Math.max(0, main.length - shown)} left)`;
    const col = filter === "all" ? items.filter(isCollapsed) : [];
    $("news-collapsed").hidden = !col.length;
    $("news-collapsed-sum").textContent = `${[...collapsedIds].map((id) => labels[id]).join(", ")}: ${col.length} more item${col.length === 1 ? "" : "s"}`;
    $("news-collapsed-list").innerHTML = col.map((i) => newsItem(i, labels)).join("");
  };
  filters.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.f; shown = NEWS_PAGE;
    filters.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    draw();
  }));
  $("news-more").onclick = () => { shown += NEWS_PAGE; draw(); };
  draw();
  srcLine("src-news", { name: `Google News RSS, last ${news.lookback_days || 90} days`, cadence: "weekly", tag: "Live", through: news.fetched_at ? fmtDate(news.fetched_at) : null });
}

// ---------- About ----------
function renderSources(F, summary) {
  const j = (summary.prices || {}).joby;
  const rows = [
    ["SRTA, TMDX and JOBY prices", "Yahoo Finance chart API", "Live", "Weekly", "scripts/fetch_price.py → data/processed/price.json"],
    ["Weekly transplants by organ", F.transplants_weekly.source, "Live", "Weekly", "scripts/fetch_optn.py → data/raw/optn/ → data/processed/transplants_weekly.json"],
    ["Deceased donors and discard rate", F.donors_weekly.source, "Live", "Weekly", "data/processed/donors_weekly.json"],
    ["Waitlist additions", F.waitlist_weekly.source, "Live", "Weekly", "data/processed/waitlist_weekly.json"],
    ["Donor mix (DBD / DCD)", F.donor_mix.source, "Live", "Monthly", "scripts/fetch_optn_national.py → data/raw/optn/national/ → data/processed/donor_mix.json"],
    ["Distance bands", F.distance.source, "Live", "Monthly", "data/processed/distance.json"],
    ["Weekly transplants by OPTN region", F.regions_weekly.source, "Live", "Weekly", "data/processed/regions_weekly.json; config/optn_regions.json"],
    ["Transplants by state", F.location.source, "Live", "Monthly snapshot", "data/processed/location.json"],
    ["Top transplant centers", F.centers.source, "Live", "Monthly", "data/processed/centers.json"],
    ["Organ-miles", "SRTA organ-miles tracker (slogatskiy.github.io/srta-organ-miles-tracker)", "Linked", "Maintained externally", "—"],
    ["U.S. overdose deaths", F.cdc_overdose.source, "Live", "Monthly", "scripts/fetch_cdc.py → data/processed/cdc_overdose.json"],
    ["SRTA quarterly KPIs", "SRTA earnings releases and filings (source per field)", "Manual", "Quarterly", "data/manual/company_kpis.json"],
    ["JOBY earn-out", j ? `${j.source} Caps: ${j.cap_source}` : "PM estimate", "Manual", "Weekly (price)", "config/holdings.json"],
    ["SEC filings", F.sec_filings.source, "Live", "Weekly", "scripts/fetch_sec.py → data/processed/sec_filings.json (needs the SEC_USER_AGENT secret)"],
    ["TransMedics quarterly KPIs", "TMDX earnings releases and filings (source per field)", "Manual", "Quarterly", "data/manual/tmdx_kpis.json"],
    ["News", F.news.source, "Live", "Weekly", "scripts/fetch_news.py → data/processed/news.json; config/keywords.json"],
    ["Signals, health check, digest", "Computed from the files above", "Live", "Weekly", "config/signals.json; config/health.json; data/weekly_summary.json; summary/latest.md"],
  ];
  $("sources-body").innerHTML = rows.map(([name, src, tag, cad, files]) =>
    `<tr><td>${esc(name)}</td><td>${esc(src || "n/a")}</td><td><span class="tier-tag ${tag.toLowerCase()}">${tag}</span></td><td>${esc(cad)}</td><td class="files"><code>${esc(files)}</code></td></tr>`).join("");
}

(async function main() {
  const names = ["transplants_weekly", "donors_weekly", "waitlist_weekly", "donor_mix", "distance", "location",
    "regions_weekly", "centers", "news", "price", "cdc_overdose", "sec_filings", "health"];
  const [summary, kpis, tmdxKpis, ...rest] = await Promise.all([
    load("data/weekly_summary.json"), load("data/manual/company_kpis.json"), load("data/manual/tmdx_kpis.json"),
    ...names.map((n) => load(`data/processed/${n}.json`)),
  ]);
  const F = Object.fromEntries(names.map((n, i) => [n, rest[i]]));
  const run = (fn) => { try { fn(); } catch (e) { console.error(e); } }; // one broken panel never blanks the page
  run(() => renderHealth(F.health));
  run(() => renderHeader(summary, F.price));
  run(() => renderSignals(summary));
  run(() => renderThisWeek(summary));
  run(() => renderVolumes(summary, F.transplants_weekly));
  run(() => renderDonors(summary, F.donors_weekly));
  run(() => renderWaitlist(summary, F.waitlist_weekly));
  run(() => renderDonorMix(F.donor_mix));
  run(() => renderDistance(F.distance));
  run(() => renderRegions(summary, F.regions_weekly));
  run(() => renderLocation(F.location));
  run(() => renderCenters(F.centers));
  run(() => renderCdc(F.cdc_overdose));
  run(() => renderKpis(kpis, "kpi-body", "src-kpis", "SRTA earnings releases and filings"));
  run(() => renderJoby(summary));
  run(() => renderSec(F.sec_filings));
  run(() => renderRelative(summary));
  run(() => renderKpis(tmdxKpis, "tmdx-kpi-body", "src-tmdx", "TransMedics earnings releases and filings"));
  run(() => renderNews(F.news));
  run(() => renderSources(F, summary));
})();
