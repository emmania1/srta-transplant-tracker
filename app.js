// SRTA Transplant Tracker — renders everything from data/*.json. No numbers live in this file.
const ORGANS = ["heart", "liver", "lung", "kidney"];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const fmtInt = (n) => (n == null ? "n/a" : n.toLocaleString("en-US"));
const fmtDate = (s) => {
  if (!s) return "n/a";
  const d = new Date(s.length <= 10 ? s + "T12:00:00Z" : s);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
};
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

function yoy(p) {
  if (p == null) return `<span class="flat">n/a</span>`;
  if (p > 0) return `<span class="up">▲ ${p.toFixed(1)}%</span>`;
  if (p < 0) return `<span class="down">▼ ${Math.abs(p).toFixed(1)}%</span>`;
  return `<span class="flat">— 0.0%</span>`;
}
function awaiting(what, src) {
  return `<div class="awaiting"><strong>Awaiting data.</strong> ${esc(what)} will appear once ${esc(src)} is loaded.</div>`;
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
  return isoWeek(r.week_start);
}
function isoWeek(weekStart) {
  const d = new Date(weekStart + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + 3); // week midpoint, matches scripts/metrics.py
  const day = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - day + 3);
  const year = d.getUTCFullYear();
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const week = 1 + Math.round(((d - jan4) / 864e5 - 3 + ((jan4.getUTCDay() + 6) % 7)) / 7);
  return { year, week };
}

// ---------- header ----------
const fmtUsd = (v, d = 2) => (v == null ? "n/a" : `$${v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`);
const fmtUsdM = (v) => (v == null ? "n/a" : `$${(v / 1e6).toFixed(1)}M`);

function renderHeader(summary, price) {
  const P = (summary.prices || {}).tickers || {};
  const tick = price.tickers || {};
  const box = (sym, valId, chgId) => {
    const p = P[sym];
    if (!p) { $(valId).textContent = "—"; $(chgId).innerHTML = `<span class="flat">Awaiting data</span>`; return; }
    $(valId).textContent = fmtUsd(p.close);
    $(chgId).innerHTML = `${yoy(p.change_1w_pct)} <span class="updated">1 wk</span>`;
  };
  box("SRTA", "price-val", "price-chg");
  box("TMDX", "tmdx-val", "tmdx-chg");
  box("JOBY", "joby-val", "joby-chg");
  const s = P.SRTA;
  if (s) {
    let u = `Close ${fmtDate(s.date)}`;
    const err = Object.entries(tick).filter(([, v]) => v.fetch_error).map(([k]) => k);
    if (err.length) u += ` · refresh failed for ${err.join(", ")}; showing last good values`;
    $("price-updated").textContent = u;
  }
  const j = (summary.prices || {}).joby;
  if (j) {
    $("joby-value").innerHTML = `${esc(j.label)}: <strong>${fmtUsdM(j.value)}</strong> (${(j.shares / 1e6).toFixed(2)}M sh × price; ${yoy(j.change_1w_pct)} 1 wk) <span class="tier-tag manual" title="${esc(j.source)}">Manual sh count</span>`;
  }
  $("page-updated").textContent = summary.generated_at ? `Last updated ${fmtDate(summary.generated_at)}` : "";
  $("digest-updated").textContent = summary.generated_at ? `Digest generated ${fmtDate(summary.generated_at)}` : "";
  const ul = $("this-week-list");
  ul.innerHTML = ((summary.bullets || []).map((b) => `<li>${esc(b)}</li>`).join("") || "<li>Digest not generated yet.</li>")
    + (summary.news_line ? `<li class="muted-li">${esc(summary.news_line)}</li>` : "");
}

function renderHealth(h) {
  const issues = (h && h.issues) || [];
  const banner = $("health-banner");
  if (issues.length) {
    banner.hidden = false;
    banner.innerHTML = `<strong>⚠ Data issue${issues.length > 1 ? "s" : ""}</strong> (checked ${fmtDate(h.checked_at)}). The page is showing the last good data.<ul>${issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
  }
  const notes = (h && h.notices) || [];
  $("health-notices").textContent = notes.length ? `Setup notes: ${notes.join(" ")}` : "";
}

function renderSignals(summary) {
  const sig = summary.signals;
  if (!sig) { $("signals-body").innerHTML = awaiting("Signal strip", "OPTN data"); return; }
  const cls = (label) => ({ up: "up", longer: "up", rising: "up", down: "down", shorter: "down", falling: "down" }[label] || "flat");
  const arrowFor = (label) => ({ up: "▲", longer: "▲", rising: "▲", down: "▼", shorter: "▼", falling: "▼" }[label] || "—");
  const num = (v, unit) => (v == null ? "n/a" : `${v > 0 ? "+" : ""}${v.toFixed(1)}${unit === "%" ? "%" : " pts"}`);
  // labels, not judgments: neutral chips with arrows + text
  const chip = (name, v) => `<span class="sig-chip"><span class="sig-name">${name}</span> <span class="sig-label">${arrowFor(v.label)} ${esc(v.label || "n/a")}</span> <span class="sig-num">${num(v.value, v.unit)}</span></span>`;
  const t = sig.thresholds;
  const rows = [
    ["Volumes", "4-wk YoY", `flat = within ±${t.volumes.flat_within_pct}%`, ORGANS.map((o) => chip(o === "kidney" ? "Kidney (incl. KP)" : cap(o), sig.volumes[o])).join("")],
    sig.distance ? ["Distance", "251+ NM share", `flat = within ±${t.distance.flat_within_pts} pt`, ORGANS.map((o) => chip(aloneLabel(o), sig.distance[o])).join("")] : null,
    sig.dcd_share ? ["DCD share", esc(sig.dcd_share.basis), `flat = within ±${t.dcd_share.flat_within_pts} pt`, chip("All deceased donors", sig.dcd_share)] : null,
    sig.discard_rate ? ["Discard rate", esc(sig.discard_rate.basis), `flat = within ±${t.discard_rate.flat_within_pts} pt`, chip("All organs", sig.discard_rate)] : null,
  ].filter(Boolean);
  $("signals-body").innerHTML = rows.map(([h, basis, rule, chips]) =>
    `<div class="sig-row"><div class="sig-head"><strong>${h}</strong><span class="updated">${basis} · ${rule}</span></div><div class="sig-chips">${chips}</div></div>`).join("");
}

// ---------- weekly organ panels (transplants, waitlist additions) ----------
// Kidney differs by source: the OPTN metrics dashboard's Kidney includes kidney-pancreas;
// OPTN national data's Kidney is kidney alone. Labels say which, everywhere.
const KIDNEY_DASH = "Kidney (incl. kidney-pancreas)";
const KIDNEY_ALONE = "Kidney (alone)";
const dashLabel = (o) => (o === "kidney" ? KIDNEY_DASH : o === "all" ? "All organs (OPTN total)" : cap(o));
const aloneLabel = (o) => (o === "kidney" ? KIDNEY_ALONE : cap(o));

function totalSeries(organs) {
  const maps = ORGANS.map((o) => new Map((organs[o] || []).map((r) => [r.week_start, r])));
  if (maps.some((m) => m.size === 0)) return [];
  return [...maps[0].keys()].filter((k) => maps.every((m) => m.has(k))).sort()
    .map((k) => ({ week_start: k, week_end: maps[0].get(k).week_end, count: maps.reduce((s, m) => s + m.get(k).count, 0) }));
}

function weeklyPanel({ id, data, metrics, what, src }) {
  // id prefix: elements `${id}-cards`, `${id}-tabs`, `${id}-chart-wrap`, `${id}-chart`, `${id}-table`
  let current = "heart", chart = null;
  const ok = data.status === "ok";
  const cardsEl = $(`${id}-cards`), tabsEl = $(`${id}-tabs`);

  const cards = () => {
    cardsEl.innerHTML = ORGANS.map((o) => {
      const m = (metrics || {})[o];
      if (!ok || !m) {
        return `<button class="card awaiting-card" data-organ="${o}" aria-pressed="${o === current}">
          <div class="organ">${dashLabel(o)}</div><div class="kpi-label">Last 4 wks vs LY</div><div class="kpi">Awaiting data</div></button>`;
      }
      const t4 = m.trailing_4wk || {}, ytd = m.ytd || {}, w = m.latest_week || {};
      return `<button class="card" data-organ="${o}" aria-pressed="${o === current}">
        <div class="organ">${dashLabel(o)}</div>
        <div class="kpi-label">Last 4 wks vs LY</div>
        <div class="kpi">${yoy(t4.yoy_pct)}</div>
        <div class="sub">${fmtInt(t4.total)} vs ${fmtInt(t4.prior_year_total)}</div>
        <div class="kpi-label">YTD vs LY</div>
        <div class="sub">${yoy(ytd.yoy_pct)} · ${fmtInt(ytd.total)}</div>
        <div class="kpi-label">Wk ending ${fmtDate(w.week_end)}</div>
        <div class="sub">${fmtInt(w.count)} (${yoy(w.yoy_pct)})</div>
      </button>`;
    }).join("");
    cardsEl.querySelectorAll(".card").forEach((b) => b.addEventListener("click", () => select(b.dataset.organ)));
  };

  const draw = () => {
    const wrap = $(`${id}-chart-wrap`);
    if (!ok) {
      wrap.style.height = "auto";
      wrap.innerHTML = awaiting(what, src);
      const tv = $(`${id}-table`)?.closest(".table-view");
      if (tv) tv.hidden = true;
      return;
    }
    const organs = data.organs || {};
    const rows = current === "all" ? (organs.all?.length ? organs.all : totalSeries(organs)) : organs[current] || [];
    const byYear = {};
    rows.forEach((r) => { const { year, week } = weekKey(r); (byYear[year] = byYear[year] || {})[week] = r.count; });
    const years = Object.keys(byYear).map(Number).sort((a, b) => b - a).slice(0, 3);
    const colors = [css("--yr0"), css("--yr1"), css("--yr2")];
    const labels = Array.from({ length: rows[0]?.yr != null ? 52 : 53 }, (_, i) => i + 1);
    const datasets = years.map((y, i) => ({
      label: `${dashLabel(current)} ${y}`,
      data: labels.map((w) => byYear[y][w] ?? null),
      borderColor: colors[i], backgroundColor: colors[i],
      borderWidth: i === 0 ? 2.5 : 1.5, pointRadius: 0, pointHoverRadius: 4, spanGaps: false, tension: 0.2,
    }));
    if (chart) chart.destroy();
    chart = new Chart($(`${id}-chart`), {
      type: "line", data: { labels, datasets },
      options: {
        maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "top", align: "end", labels: { color: css("--text-2"), boxWidth: 14, boxHeight: 2 } },
          tooltip: { callbacks: { title: (it) => `Week ${it[0].label}`, label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } },
        },
        scales: {
          x: { title: { display: true, text: "Week of year (OPTN: week 1 starts Jan 1)", color: css("--muted") }, ticks: { color: css("--muted"), maxTicksLimit: 14 }, grid: { display: false } },
          y: { ticks: { color: css("--muted"), callback: (v) => fmtInt(v) }, grid: { color: css("--grid") } },
        },
      },
    });
    $(`${id}-table`).innerHTML = `<div class="scroll-x"><table><thead><tr><th>Week</th>${years.map((y) => `<th>${y}</th>`).join("")}</tr></thead><tbody>${
      labels.filter((w) => years.some((y) => byYear[y][w] != null)).reverse()
        .map((w) => `<tr><td>W${w}</td>${years.map((y) => `<td>${fmtInt(byYear[y][w] ?? null)}</td>`).join("")}</tr>`).join("")
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
  draw();
}

function renderVolumes(summary, tw) {
  $("vol-updated").textContent = tw.status === "ok" ? `OPTN pull ${fmtDate(tw.data_as_of)}` : "Awaiting first OPTN file";
  weeklyPanel({ id: "vol", data: tw, metrics: (summary.optn || {}).organs, what: "Weekly transplant volumes by organ", src: "the OPTN metrics download" });
}

function renderWaitlist(summary, wl) {
  $("wl-updated").textContent = wl.status === "ok" ? `OPTN pull ${fmtDate(wl.data_as_of)}` : "Awaiting first OPTN file";
  weeklyPanel({ id: "wl", data: wl, metrics: summary.waitlist, what: "Weekly waitlist additions by organ", src: "the OPTN metrics waitlist download" });
}

function renderDonorLine(summary, dw) {
  const el = $("donor-line");
  const d = summary.donors;
  if (dw.status !== "ok" || !d || !d.metrics) {
    el.innerHTML = `<span><strong>Deceased donors recovered:</strong> awaiting data</span>`;
    return;
  }
  const t4 = d.metrics.trailing_4wk || {}, ytd = d.metrics.ytd || {}, w = d.metrics.latest_week || {};
  let html = `<span><strong>Context: deceased donors recovered</strong> · last 4 wks ${fmtInt(t4.total)} vs ${fmtInt(t4.prior_year_total)} ${yoy(t4.yoy_pct)}</span>
    <span>YTD ${yoy(ytd.yoy_pct)}</span>
    <span>Wk ending ${fmtDate(w.week_end)}: ${fmtInt(w.count)} (${yoy(w.yoy_pct)})</span>`;
  const disc = d.discard;
  if (disc) {
    // discard rate: arrow + text only, no green/red (a rising discard rate is not "good")
    const ch = disc.change_pts;
    const chTxt = ch == null ? "n/a" : `${ch > 0 ? "▲" : ch < 0 ? "▼" : "—"} ${Math.abs(ch).toFixed(1)} pts`;
    html += `<span><strong>All-organs discard rate</strong> (YTD through ${esc(disc.through)}): ${disc.discard_rate_pct.toFixed(1)}% vs ${disc.prior_year_discard_rate_pct == null ? "n/a" : disc.prior_year_discard_rate_pct.toFixed(1) + "%"} LY (${chTxt})</span>`;
  }
  el.innerHTML = html;
}

// ---------- donor mix / distance / location (normalized schemas, see README) ----------
function updatedLabel(d) {
  if (d.status !== "ok") return "Awaiting first OPTN file";
  return `OPTN monthly data through ${fmtDate(d.period_end)} · as of ${fmtDate(d.data_as_of)}`;
}
function ptsChange(v) {
  // neutral styling: a share shift isn't good or bad by itself
  if (v == null) return "n/a";
  return `${v > 0 ? "▲" : v < 0 ? "▼" : "—"} ${Math.abs(v).toFixed(1)} pts`;
}
const pctTxt = (v) => (v == null ? "n/a" : `${v.toFixed(1)}%`);
const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5"];

let mixChart = null;
function renderDonorMix(d) {
  $("mix-updated").textContent = updatedLabel(d);
  if (d.status !== "ok") { $("mix-body").innerHTML = awaiting("DBD vs. DCD donor counts and DCD share by organ", "the OPTN national data"); return; }
  const cy = String(d.current_year), py = String(d.prior_year);
  const rows = [["All deceased donors", d.donors], ...ORGANS.map((o) => [`${aloneLabel(o)} transplants`, d.transplants_by_organ[o]])];
  const tbl = rows.map(([name, v]) => {
    const c = v[cy], p = v[py];
    const ch = c.dcd_share_pct != null && p.dcd_share_pct != null ? Math.round(10 * (c.dcd_share_pct - p.dcd_share_pct)) / 10 : null;
    return `<tr><td>${name}</td><td>${fmtInt(c.dcd)} / ${fmtInt(c.total)}</td><td><strong>${pctTxt(c.dcd_share_pct)}</strong></td><td>${pctTxt(p.dcd_share_pct)}</td><td>${ptsChange(ch)}</td></tr>`;
  }).join("");
  $("mix-body").innerHTML = `
    <div class="scroll-x"><table>
      <thead><tr><th></th><th>DCD / total, ${esc(d.current_label)}</th><th>DCD share, ${esc(d.current_label)}</th><th>DCD share, ${esc(d.prior_label)}</th><th>Change</th></tr></thead>
      <tbody>${tbl}</tbody></table></div>
    <h3 class="sub-head">DCD share by year</h3>
    <div class="chart-wrap short"><canvas id="mix-chart" aria-label="DCD share by year"></canvas></div>
    <p class="note">${d.current_year} is year to date (through ${fmtDate(d.period_end)}). ${KIDNEY_ALONE}: OPTN national data counts kidney-pancreas separately, unlike the weekly volume panel.</p>`;
  const years = d.years.map(String);
  const datasets = rows.map(([name, v], i) => ({
    label: name.replace(" transplants", ""),
    data: years.map((y) => v[y]?.dcd_share_pct ?? null),
    borderColor: css(SERIES[i]), backgroundColor: css(SERIES[i]),
    borderWidth: i === 0 ? 2.5 : 1.75, pointRadius: years.map((y) => (y === cy ? 4 : 2)),
    pointStyle: years.map((y) => (y === cy ? "rectRot" : "circle")), tension: 0,
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
        x: { ticks: { color: css("--muted") }, grid: { display: false } },
        y: { ticks: { color: css("--muted"), callback: (v) => v + "%" }, grid: { color: css("--grid") } },
      },
    },
  });
}

let distChart = null;
function renderDistance(d) {
  $("dist-updated").textContent = updatedLabel(d);
  if (d.status !== "ok") { $("dist-body").innerHTML = awaiting("Distance-band shares by organ", "the OPTN national data"); return; }
  const cy = String(d.current_year), py = String(d.prior_year);
  const bands = d.band_order;
  const tbl = ORGANS.map((o) => {
    const c = d.organs[o][cy], p = d.organs[o][py];
    const ch = c.long_share_pct != null && p.long_share_pct != null ? Math.round(10 * (c.long_share_pct - p.long_share_pct)) / 10 : null;
    const cells = (x) => bands.map((b) => `<td>${pctTxt(x.shares_pct[b])}</td>`).join("");
    return `<tr><td rowspan="2"><strong>${aloneLabel(o)}</strong></td><td>${esc(d.current_label)}</td>${cells(c)}<td rowspan="2"><strong>${pctTxt(c.long_share_pct)}</strong> vs ${pctTxt(p.long_share_pct)}<br>${ptsChange(ch)}</td></tr>
            <tr class="prior"><td>${esc(d.prior_label)}</td>${cells(p)}</tr>`;
  }).join("");
  $("dist-body").innerHTML = `
    <div class="chart-wrap tall"><canvas id="dist-chart" aria-label="Distance band shares by organ"></canvas></div>
    <details class="table-view"><summary>Show as table</summary><div class="scroll-x"><table class="dist-table">
      <thead><tr><th>Organ</th><th>Period</th>${bands.map((b) => `<th>${esc(b)} NM</th>`).join("")}<th>251+ NM share</th></tr></thead>
      <tbody>${tbl}</tbody></table></div></details>
    <p class="note">${py} = full year; ${cy} YTD = ${esc(d.current_label.replace(/^\d{4} YTD /, ""))}. Shares exclude transplants with an unknown distance (none in these periods). ${KIDNEY_ALONE}: kidney-pancreas is a separate OPTN category here.</p>`;
  const labels = ORGANS.flatMap((o) => [`${aloneLabel(o)} ${py}`, `${aloneLabel(o)} ${cy} YTD`]);
  const bandColors = ["--band-1", "--band-2", "--band-3", "--band-4", "--band-5"];
  const datasets = bands.map((b, i) => ({
    label: `${b} NM`,
    data: ORGANS.flatMap((o) => [d.organs[o][py].shares_pct[b], d.organs[o][cy].shares_pct[b]]),
    backgroundColor: css(bandColors[i]), borderColor: css("--panel"), borderWidth: 1, borderSkipped: false,
  }));
  if (distChart) distChart.destroy();
  distChart = new Chart($("dist-chart"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      indexAxis: "y", maintainAspectRatio: false,
      plugins: {
        legend: { position: "top", align: "start", labels: { color: css("--text-2"), boxWidth: 12 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${pctTxt(c.parsed.x)}` } },
      },
      scales: {
        x: { stacked: true, max: 100, ticks: { color: css("--muted"), callback: (v) => v + "%" }, grid: { color: css("--grid") } },
        y: { stacked: true, ticks: { color: css("--text-2"), font: { size: 11 } }, grid: { display: false } },
      },
    },
  });
}

function renderRegions(summary, rw) {
  $("reg-updated").textContent = rw.status === "ok" ? `OPTN pull ${fmtDate(rw.data_as_of)}` : "Awaiting first OPTN file";
  const reg = (summary.regions || {}).regions;
  if (rw.status !== "ok" || !reg) { $("reg-body").innerHTML = awaiting("Weekly transplants by OPTN region", "the OPTN metrics region download"); return; }
  const states = rw.region_states || {};
  const rows = Object.entries(reg).filter(([, m]) => m).sort((a, b) => (b[1].trailing_4wk?.total ?? 0) - (a[1].trailing_4wk?.total ?? 0));
  const lw = rows[0]?.[1]?.latest_week;
  $("reg-body").innerHTML = `<div class="scroll-x"><table>
    <thead><tr><th>Region</th><th>Last 4 wks</th><th>Same wks LY</th><th>YoY</th><th>YTD YoY</th><th>Wk ending ${fmtDate(lw?.week_end)}</th></tr></thead>
    <tbody>${rows.map(([r, m]) => `<tr>
      <td><strong>Region ${esc(r)}</strong><div class="cell-sub">${esc((states[r] || []).join(", "))}</div></td>
      <td>${fmtInt(m.trailing_4wk?.total)}</td><td>${fmtInt(m.trailing_4wk?.prior_year_total)}</td>
      <td>${yoy(m.trailing_4wk?.yoy_pct)}</td><td>${yoy(m.ytd?.yoy_pct)}</td>
      <td>${fmtInt(m.latest_week?.count)} (${yoy(m.latest_week?.yoy_pct)})</td></tr>`).join("")}</tbody></table></div>
    <p class="note">Region membership from OPTN's region pages (${esc(rw.region_states_source || "")}).</p>`;
}

const STATE_ROWS = 15;
function renderLocation(d) {
  $("loc-updated").textContent = updatedLabel(d);
  if (d.status !== "ok") { $("loc-body").innerHTML = awaiting("Transplants by transplant-center state", "the OPTN national data"); return; }
  $("loc-note").innerHTML = `Deceased-donor transplants, all organs, by state of transplant center: ${esc(d.current_label)} vs. ${esc(d.prior_label)}. `
    + (d.yoy_available ? esc(d.yoy_note)
      : `<strong>Shares only for now.</strong> OPTN's state data is annual, so a % change would compare part of a year with a full year. A snapshot is saved every month; ${esc(d.yoy_note.replace(/^True YoY/, "a true year-over-year column"))}`);
  let shown = STATE_ROWS;
  const draw = () => {
    const rows = d.rows.slice(0, shown);
    $("loc-body").innerHTML = `<div class="scroll-x"><table>
      <thead><tr><th>State</th><th>${esc(d.current_label)}</th><th>Share</th><th>${esc(d.prior_label)}</th><th>Share</th><th>Share change</th>${d.yoy_available ? "<th>YoY (same period)</th>" : ""}</tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${esc(r.state)}</td><td>${fmtInt(r.ytd)}</td><td><strong>${pctTxt(r.share_pct)}</strong></td><td>${fmtInt(r.prior_full_year)}</td><td>${pctTxt(r.prior_share_pct)}</td>
        <td>${ptsChange(r.share_pct != null && r.prior_share_pct != null ? Math.round(10 * (r.share_pct - r.prior_share_pct)) / 10 : null)}</td>
        ${d.yoy_available ? `<td>${yoy(r.yoy_pct)}</td>` : ""}</tr>`).join("")}
      <tr class="total"><td>U.S. total</td><td>${fmtInt(d.national_ytd)}</td><td>100%</td><td>${fmtInt(d.national_prior_full_year)}</td><td>100%</td><td></td>${d.yoy_available ? "<td></td>" : ""}</tr>
      </tbody></table></div>
      ${d.rows.length > shown ? `<button class="more" id="loc-more">Show all ${d.rows.length} states</button>` : ""}
      <p class="note">${d.snapshots.length} monthly snapshot${d.snapshots.length === 1 ? "" : "s"} saved (first through ${fmtDate(d.snapshots[0].period_end)}).</p>`;
    const more = $("loc-more");
    if (more) more.onclick = () => { shown = d.rows.length; draw(); };
  };
  draw();
}

// ---------- news ----------
const NEWS_PAGE = 25;
function newsItem(i, labels) {
  const href = i.publisher_url || i.url;
  return `<li>
    <a href="${esc(href)}" target="_blank" rel="noopener">${esc(i.headline)}</a>
    <div class="news-meta">${esc(i.source)} · ${fmtDate(i.date)} ${i.tags.map((t) => `<span class="chip">${esc(labels[t] || t)}</span>`).join("")}${i.publisher_url ? "" : ` <a class="gn" href="${esc(i.url)}" target="_blank" rel="noopener">via Google News</a>`}</div>
  </li>`;
}
function renderNews(news) {
  $("news-updated").textContent = news.fetched_at ? `Fetched ${fmtDate(news.fetched_at)} · last ${news.lookback_days} days` : "Awaiting first fetch";
  const items = news.items || [];
  const groups = news.groups || [];
  const labels = Object.fromEntries(groups.map((g) => [g.id, g.label]));
  const collapsedIds = new Set(groups.filter((g) => g.collapsed).map((g) => g.id));
  // an item goes to the collapsed section only if ALL its tags are collapsed groups
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
    const col = filter === "all" ? items.filter(isCollapsed) : [];
    $("news-collapsed").hidden = !col.length;
    $("news-collapsed-sum").textContent = `${[...collapsedIds].map((id) => labels[id]).join(", ")}: ${col.length} more item${col.length === 1 ? "" : "s"} (collapsed so they don't crowd the feed)`;
    $("news-collapsed-list").innerHTML = col.map((i) => newsItem(i, labels)).join("");
  };
  filters.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.f; shown = NEWS_PAGE;
    filters.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    draw();
  }));
  $("news-more").onclick = () => { shown += NEWS_PAGE; draw(); };
  if (news.errors?.length) $("news-updated").textContent += ` · ${news.errors.length} query error(s) last run`;
  draw();
}

// ---------- centers ----------
function renderCenters(d) {
  $("ctr-updated").textContent = d.status === "ok" ? `OPTN data through ${fmtDate(d.period_end)} · as of ${fmtDate(d.data_as_of)}` : "Awaiting OPTN data";
  if (d.status !== "ok") { $("ctr-body").innerHTML = awaiting("Transplant center volumes", "the OPTN national data"); return; }
  const fy = d.full_year, py = d.comparison_year;
  $("ctr-note").textContent = `Deceased-donor heart + liver + lung transplants by transplant center, ranked by ${fy}. ${d.yoy_note} ${d.centers_with_volume} centers had volume in ${fy}.`;
  $("ctr-body").innerHTML = `<div class="scroll-x"><table>
    <thead><tr><th>#</th><th>Center</th><th>${fy}</th><th>${py}</th><th>YoY (${fy} vs ${py})</th><th>Heart / Liver / Lung ${fy}</th><th>${d.current_year} YTD</th></tr></thead>
    <tbody>${d.rows.map((r, i) => `<tr><td>${i + 1}</td><td><strong>${esc(r.center)}</strong><div class="cell-sub">${esc(r.center_code)}</div></td>
      <td>${fmtInt(r["total_" + fy])}</td><td>${fmtInt(r["total_" + py])}</td><td>${yoy(r.yoy_pct)}</td>
      <td>${["heart", "liver", "lung"].map((o) => fmtInt(r.organs[o]?.[String(fy)] ?? 0)).join(" / ")}</td>
      <td>${fmtInt(r.total_ytd)}</td></tr>`).join("")}</tbody></table></div>`;
}

// ---------- CDC ----------
let cdcChart = null;
function renderCdc(d) {
  if (d.status !== "ok") { $("cdc-body").innerHTML = awaiting("12-month rolling overdose deaths", "the CDC VSRR dataset"); return; }
  $("cdc-updated").textContent = `CDC dataset updated ${fmtDate(d.dataset_updated)}${d.fetch_error ? " · last refresh failed" : ""}`;
  const s = d.series.filter((x) => x.year >= d.series[d.series.length - 1].year - 5);
  const last = d.series[d.series.length - 1];
  const mlabel = (x) => new Date(Date.UTC(x.year, x.month - 1, 15)).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
  $("cdc-body").innerHTML = `
    <div class="context-line"><span><strong>12 months ending ${mlabel(last)}:</strong> ${fmtInt(last.predicted)} predicted (${yoy(last.predicted_yoy_pct)} YoY) · ${fmtInt(last.reported)} reported (${yoy(last.reported_yoy_pct)} YoY)</span></div>
    <div class="chart-wrap short"><canvas id="cdc-chart" aria-label="12-month rolling overdose deaths"></canvas></div>
    <p class="note">${esc(d.note)} Lower overdose deaths mean fewer potential brain-death donors; this is context, not a forecast.</p>`;
  if (cdcChart) cdcChart.destroy();
  cdcChart = new Chart($("cdc-chart"), {
    type: "line",
    data: { labels: s.map(mlabel), datasets: [
      { label: "Predicted (adjusted for reporting delay)", data: s.map((x) => x.predicted), borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2.5, pointRadius: 0 },
      { label: "Reported", data: s.map((x) => x.reported), borderColor: css("--yr2"), backgroundColor: css("--yr2"), borderWidth: 1.5, pointRadius: 0, borderDash: [4, 3] },
    ] },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top", align: "end", labels: { color: css("--text-2"), boxWidth: 14, boxHeight: 2 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } } },
      scales: { x: { ticks: { color: css("--muted"), maxTicksLimit: 8 }, grid: { display: false } },
        y: { ticks: { color: css("--muted"), callback: (v) => fmtInt(v) }, grid: { color: css("--grid") } } } },
  });
}

// ---------- manual KPIs ----------
function fmtKpi(v, unit) {
  if (v == null) return `<span class="awaiting-inline">awaiting data</span>`;
  if (unit === "$M") return `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
  if (unit === "%") return `${Number(v).toFixed(1)}%`;
  return fmtInt(Number(v));
}
function renderKpis(d, bodyId, updatedId) {
  const periods = d.periods || [];
  if (updatedId) $(updatedId).textContent = periods.length ? `Latest: ${periods[periods.length - 1].period}` : "Awaiting first quarter";
  if (!d.fields) { $(bodyId).innerHTML = awaiting("KPIs", "the manual KPI file"); return; }
  const last = periods[periods.length - 1];
  const groups = [...new Set(d.fields.map((f) => f.group))];
  $(bodyId).innerHTML = `${periods.length ? "" : `<p class="note">No quarters entered yet. Fill <code>${bodyId === "kpi-body" ? "data/manual/company_kpis.json" : "data/manual/tmdx_kpis.json"}</code> after each earnings report; every field needs a source and date.</p>`}
    <div class="scroll-x"><table class="kpi-table"><thead><tr><th>Metric</th><th>${last ? esc(last.period) : "Latest quarter"}</th><th>Source</th><th>Date</th></tr></thead><tbody>
    ${groups.map((g) => `<tr class="grp"><td colspan="4">${esc(g)}</td></tr>` + d.fields.filter((f) => f.group === g).map((f) => {
      const v = last ? (last.values || {})[f.key] || {} : {};
      return `<tr><td>${esc(f.label)}</td><td>${fmtKpi(v.value, f.unit)}</td><td class="src">${esc(v.source || "—")}</td><td>${v.date ? fmtDate(v.date) : "—"}</td></tr>`;
    }).join("")).join("")}
    </tbody></table></div>`;
}

// ---------- SRTA vs TMDX ----------
let relChart = null;
function renderRelative(summary) {
  const r = (summary.prices || {}).relative_3m;
  if (!r) { $("rel-updated").textContent = "Awaiting prices"; return; }
  $("rel-updated").textContent = `${fmtDate(r.base_date)} = 100 · SRTA ${r.srta_minus_tmdx_pts >= 0 ? "ahead of" : "behind"} TMDX by ${Math.abs(r.srta_minus_tmdx_pts).toFixed(1)} pts`;
  if (relChart) relChart.destroy();
  relChart = new Chart($("rel-chart"), {
    type: "line",
    data: { labels: r.dates.map((d) => fmtDate(d).replace(/, \d{4}$/, "")), datasets: [
      { label: "SRTA", data: r.SRTA, borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2.5, pointRadius: 0 },
      { label: "TMDX", data: r.TMDX, borderColor: css("--s2"), backgroundColor: css("--s2"), borderWidth: 2, pointRadius: 0 },
    ] },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top", align: "end", labels: { color: css("--text-2"), boxWidth: 14, boxHeight: 2 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}` } } },
      scales: { x: { ticks: { color: css("--muted"), maxTicksLimit: 7 }, grid: { display: false } },
        y: { ticks: { color: css("--muted") }, grid: { color: css("--grid") } } } },
  });
}

// ---------- SEC ----------
function renderSec(d) {
  if (d.status === "not_configured" && !(d.filings || []).length) {
    $("sec-body").innerHTML = awaiting("SRTA SEC filings", "the SEC_USER_AGENT secret is set (SEC requires a contact email)"); return;
  }
  if (!(d.filings || []).length) { $("sec-body").innerHTML = awaiting("SRTA SEC filings", "the SEC EDGAR fetch"); return; }
  $("sec-updated").textContent = `Fetched ${fmtDate(d.fetched_at)}${d.fetch_error ? " · last refresh failed" : ""}${d.config_note ? " · not refreshing: " + d.config_note : ""}`;
  const kind = (f) => (f.form.startsWith("4") ? "Form 4" : /13[DG]/.test(f.form) ? "13D / 13G" : f.form.replace("/A", ""));
  const kinds = [...new Set(d.filings.map(kind))];
  let filter = "all";
  const draw = () => {
    const rows = d.filings.filter((f) => filter === "all" || kind(f) === filter);
    $("sec-body").innerHTML = `<div class="scroll-x"><table><thead><tr><th>Filed</th><th>Form</th><th>Description</th><th></th></tr></thead><tbody>${
      rows.map((f) => {
        const f4 = f.form4;
        let desc = esc(f.description);
        if (f.items) desc += ` <span class="cell-sub">Items ${esc(f.items)}</span>`;
        if (f4) desc = `${esc(f4.owner)}${f4.roles.length ? ` (${esc(f4.roles.join(", "))})` : ""}: ${f4.transactions.map((t) => `${esc(t.code)} ${fmtInt(t.shares)}`).join(", ") || "no non-derivative transactions"}`
          + (f4.open_market_sale ? ` <span class="flag">open-market sale ${fmtInt(f4.shares_sold)} sh</span>` : "");
        if (/13D/.test(f.form)) desc += ` <span class="flag">13D</span>`;
        return `<tr><td>${fmtDate(f.filed)}</td><td>${esc(f.form)}</td><td class="desc">${desc}</td><td><a href="${esc(f.url)}" target="_blank" rel="noopener">Filing ↗</a></td></tr>`;
      }).join("")}</tbody></table></div>
      <p class="note">Form 4 codes: S = open-market sale, P = purchase, A = grant/award, F = shares withheld for taxes, M = option exercise.</p>`;
  };
  $("sec-filters").innerHTML = ["all", ...kinds].map((k) => `<button data-k="${esc(k)}" aria-pressed="${k === "all"}">${k === "all" ? "All" : esc(k)} (${k === "all" ? d.filings.length : d.filings.filter((f) => kind(f) === k).length})</button>`).join("");
  $("sec-filters").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.k; $("sec-filters").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw();
  }));
  draw();
}

// ---------- footer ----------
const CADENCE2 = {
  price: "Weekly (Sun) via GitHub Action",
  transplants_weekly: "Weekly (Sun) via GitHub Action",
  donors_weekly: "Weekly (Sun) via GitHub Action",
  waitlist_weekly: "Weekly (Sun) via GitHub Action",
  regions_weekly: "Weekly (Sun) via GitHub Action",
  donor_mix: "Monthly (OPTN refresh); checked every Sunday",
  distance: "Monthly (OPTN refresh); checked every Sunday",
  location: "Monthly snapshot (OPTN refresh); checked every Sunday",
  centers: "Monthly (OPTN refresh); checked every Sunday",
  cdc: "Monthly (CDC refresh); checked every Sunday",
  sec: "Weekly (Sun) via GitHub Action",
  news: "Weekly (Sun) via GitHub Action; 90-day window",
  kpis: "Quarterly, after earnings (hand-entered)",
};
function renderSources(files, summary) {
  const j = (summary.prices || {}).joby;
  const rows = [
    ["SRTA, TMDX, JOBY share prices", files.price, "price"],
    ["Weekly transplants by organ", files.transplants_weekly, "transplants_weekly"],
    ["Deceased donors recovered + discard rate", files.donors_weekly, "donors_weekly"],
    ["Weekly waitlist additions by organ", files.waitlist_weekly, "waitlist_weekly"],
    ["Donor mix (DBD / DCD)", files.donor_mix, "donor_mix"],
    ["Distance bands", files.distance, "distance"],
    ["Weekly transplants by OPTN region", files.regions_weekly, "regions_weekly"],
    ["Transplants by state (monthly snapshots)", files.location, "location"],
    ["Top transplant centers", files.centers, "centers"],
    ["U.S. overdose deaths", files.cdc, "cdc"],
    ["SRTA SEC filings", files.sec, "sec"],
    ["News & company mentions", files.news, "news"],
    ["SRTA company KPIs", { source: "data/manual/company_kpis.json (SRTA earnings releases and filings; source per field)", tag: "Manual" }, "kpis"],
    ["TransMedics KPIs", { source: "data/manual/tmdx_kpis.json (TMDX earnings releases and filings; source per field)", tag: "Manual" }, "kpis"],
  ];
  if (j) rows.splice(1, 0, ["JOBY share count for contingent-consideration value", { source: j.source, tag: "Manual" }, "kpis"]);
  $("sources-body").innerHTML = rows.map(([name, f, key]) => {
    const tag = (f && f.tag) || "—";
    return `<tr><td>${name}</td><td>${esc((f && f.source) || "n/a")}</td><td><span class="tier-tag ${tag.toLowerCase()}">${esc(tag)}</span></td><td>${CADENCE2[key] || ""}</td></tr>`;
  }).join("") + `<tr><td>Organ-miles</td><td><a href="https://slogatskiy.github.io/srta-organ-miles-tracker/" target="_blank" rel="noopener">SRTA organ-miles tracker</a></td><td><span class="tier-tag linked">Linked</span></td><td>Maintained externally</td></tr>`;
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
  run(() => renderVolumes(summary, F.transplants_weekly));
  run(() => renderDonorLine(summary, F.donors_weekly));
  run(() => renderWaitlist(summary, F.waitlist_weekly));
  run(() => renderDonorMix(F.donor_mix));
  run(() => renderDistance(F.distance));
  run(() => renderRegions(summary, F.regions_weekly));
  run(() => renderLocation(F.location));
  run(() => renderCenters(F.centers));
  run(() => renderCdc(F.cdc_overdose));
  run(() => renderKpis(kpis, "kpi-body", "kpi-updated"));
  run(() => renderRelative(summary));
  run(() => renderKpis(tmdxKpis, "tmdx-kpi-body", null));
  run(() => renderSec(F.sec_filings));
  run(() => renderNews(F.news));
  run(() => renderSources({ price: F.price, transplants_weekly: F.transplants_weekly, donors_weekly: F.donors_weekly,
    waitlist_weekly: F.waitlist_weekly, donor_mix: F.donor_mix, distance: F.distance, regions_weekly: F.regions_weekly,
    location: F.location, centers: F.centers, cdc: F.cdc_overdose, sec: F.sec_filings, news: F.news }, summary));
})();
