// SRTA Transplant Tracker — renders everything from data/*.json. No numbers live in this file.
const ORGANS = ["heart", "liver", "lung", "kidney"];
const CADENCE = {
  price: "Weekly (Sun) via GitHub Action",
  news: "Weekly (Sun) via GitHub Action; 90-day window",
  transplants_weekly: "Weekly (Sun) via GitHub Action",
  donors_weekly: "Weekly (Sun) via GitHub Action",
  donor_mix: "Monthly (OPTN refresh); checked every Sunday",
  distance: "Monthly (OPTN refresh); checked every Sunday",
  regions_weekly: "Weekly (Sun) via GitHub Action",
  location: "Monthly snapshot (OPTN refresh); checked every Sunday",
};

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
function renderHeader(summary, price) {
  const p = summary.price;
  if (!p) {
    $("price-val").textContent = "—";
    $("price-chg").innerHTML = `<span class="flat">Awaiting data</span>`;
  } else {
    $("price-val").textContent = `$${p.close.toFixed(2)}`;
    $("price-chg").innerHTML = `${yoy(p.change_1w_pct)} <span class="updated">1 wk</span>`;
    let u = `Close ${fmtDate(p.date)}`;
    if (price.fetch_error) u += ` · last refresh failed ${fmtDate(price.fetch_error.at)}, showing last good value`;
    $("price-updated").textContent = u;
  }
  $("page-updated").textContent = summary.generated_at ? `Last updated ${fmtDate(summary.generated_at)}` : "";
  $("digest-updated").textContent = summary.generated_at ? `Digest generated ${fmtDate(summary.generated_at)}` : "";
  const ul = $("this-week-list");
  ul.innerHTML = ((summary.bullets || []).map((b) => `<li>${esc(b)}</li>`).join("") || "<li>Digest not generated yet.</li>")
    + (summary.news_line ? `<li class="muted-li">${esc(summary.news_line)}</li>` : "");
}

// ---------- volumes ----------
let volChart = null;
let currentOrgan = "heart";

function renderCards(summary, tw) {
  const organs = (summary.optn || {}).organs || {};
  const ok = tw.status === "ok";
  $("organ-cards").innerHTML = ORGANS.map((o) => {
    const m = organs[o];
    if (!ok || !m) {
      return `<button class="card awaiting-card" data-organ="${o}" aria-pressed="${o === currentOrgan}">
        <div class="organ">${cap(o)}</div><div class="kpi-label">Last 4 wks vs LY</div>
        <div class="kpi">Awaiting data</div></button>`;
    }
    const t4 = m.trailing_4wk || {}, ytd = m.ytd || {}, w = m.latest_week || {};
    return `<button class="card" data-organ="${o}" aria-pressed="${o === currentOrgan}">
      <div class="organ">${cap(o)}</div>
      <div class="kpi-label">Last 4 wks vs LY</div>
      <div class="kpi">${yoy(t4.yoy_pct)}</div>
      <div class="sub">${fmtInt(t4.total)} vs ${fmtInt(t4.prior_year_total)}</div>
      <div class="kpi-label">YTD vs LY</div>
      <div class="sub">${yoy(ytd.yoy_pct)} · ${fmtInt(ytd.total)}</div>
      <div class="kpi-label">Wk ending ${fmtDate(w.week_end)}</div>
      <div class="sub">${fmtInt(w.count)} (${yoy(w.yoy_pct)})</div>
    </button>`;
  }).join("");
  $("organ-cards").querySelectorAll(".card").forEach((b) =>
    b.addEventListener("click", () => selectOrgan(b.dataset.organ, tw)));
}

function totalSeries(organs) {
  const maps = ORGANS.map((o) => new Map((organs[o] || []).map((r) => [r.week_start, r])));
  if (maps.some((m) => m.size === 0)) return [];
  return [...maps[0].keys()].filter((k) => maps.every((m) => m.has(k))).sort()
    .map((k) => ({ week_start: k, week_end: maps[0].get(k).week_end, count: maps.reduce((s, m) => s + m.get(k).count, 0) }));
}

function selectOrgan(organ, tw) {
  currentOrgan = organ;
  document.querySelectorAll("#organ-cards .card").forEach((c) => c.setAttribute("aria-pressed", c.dataset.organ === organ));
  document.querySelectorAll("#organ-tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.organ === organ));
  drawVolumes(tw);
}

function drawVolumes(tw) {
  const wrap = $("vol-chart-wrap");
  if (tw.status !== "ok") {
    wrap.style.height = "auto";
    wrap.innerHTML = awaiting("Weekly transplant volumes by organ", "the first OPTN metrics export");
    document.querySelector("#volumes .table-view").hidden = true;
    return;
  }
  const organs = tw.organs || {};
  const rows = currentOrgan === "all" ? (organs.all?.length ? organs.all : totalSeries(organs)) : organs[currentOrgan] || [];
  const byYear = {};
  rows.forEach((r) => {
    const { year, week } = weekKey(r);
    (byYear[year] = byYear[year] || {})[week] = r.count;
  });
  const years = Object.keys(byYear).map(Number).sort((a, b) => b - a).slice(0, 3);
  const colors = [css("--yr0"), css("--yr1"), css("--yr2")];
  const labels = Array.from({ length: years.length && rows[0]?.yr != null ? 52 : 53 }, (_, i) => i + 1);
  const datasets = years.map((y, i) => ({
    label: String(y),
    data: labels.map((w) => byYear[y][w] ?? null),
    borderColor: colors[i], backgroundColor: colors[i],
    borderWidth: i === 0 ? 2.5 : 1.5, pointRadius: 0, pointHoverRadius: 4, spanGaps: false, tension: 0.2,
  }));
  if (volChart) volChart.destroy();
  volChart = new Chart($("vol-chart"), {
    type: "line",
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "top", align: "end", labels: { color: css("--text-2"), boxWidth: 14, boxHeight: 2 } },
        tooltip: { callbacks: { title: (it) => `Week ${it[0].label}`, label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } },
      },
      scales: {
        x: { title: { display: true, text: rows[0]?.yr != null ? "Week of year (OPTN: week 1 starts Jan 1)" : "ISO week", color: css("--muted") }, ticks: { color: css("--muted"), maxTicksLimit: 14 }, grid: { display: false } },
        y: { ticks: { color: css("--muted"), callback: (v) => fmtInt(v) }, grid: { color: css("--grid") } },
      },
    },
  });
  // table view
  $("vol-table").innerHTML = `<div class="scroll-x"><table><thead><tr><th>Week</th>${years.map((y) => `<th>${y}</th>`).join("")}</tr></thead><tbody>${
    labels.filter((w) => years.some((y) => byYear[y][w] != null)).reverse()
      .map((w) => `<tr><td>W${w}</td>${years.map((y) => `<td>${fmtInt(byYear[y][w] ?? null)}</td>`).join("")}</tr>`).join("")
  }</tbody></table></div>`;
}

function renderVolumes(summary, tw) {
  $("vol-updated").textContent = tw.status === "ok"
    ? `OPTN pull ${fmtDate(tw.data_as_of)}` : "Awaiting first OPTN file";
  renderCards(summary, tw);
  $("organ-tabs").innerHTML = [...ORGANS, "all"].map((o) =>
    `<button role="tab" data-organ="${o}" aria-selected="${o === currentOrgan}">${o === "all" ? "All organs (OPTN total)" : cap(o)}</button>`).join("");
  $("organ-tabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => selectOrgan(b.dataset.organ, tw)));
  drawVolumes(tw);
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
  const rows = [["All deceased donors", d.donors], ...ORGANS.map((o) => [`${cap(o)} transplants`, d.transplants_by_organ[o]])];
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
    <p class="note">${d.current_year} is year to date (through ${fmtDate(d.period_end)}). Kidney here is kidney alone; kidney-pancreas is a separate OPTN category.</p>`;
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
    return `<tr><td rowspan="2"><strong>${cap(o)}</strong></td><td>${esc(d.current_label)}</td>${cells(c)}<td rowspan="2"><strong>${pctTxt(c.long_share_pct)}</strong> vs ${pctTxt(p.long_share_pct)}<br>${ptsChange(ch)}</td></tr>
            <tr class="prior"><td>${esc(d.prior_label)}</td>${cells(p)}</tr>`;
  }).join("");
  $("dist-body").innerHTML = `
    <div class="chart-wrap tall"><canvas id="dist-chart" aria-label="Distance band shares by organ"></canvas></div>
    <details class="table-view" open><summary>Table</summary><div class="scroll-x"><table class="dist-table">
      <thead><tr><th>Organ</th><th>Period</th>${bands.map((b) => `<th>${esc(b)} NM</th>`).join("")}<th>251+ NM share</th></tr></thead>
      <tbody>${tbl}</tbody></table></div></details>
    <p class="note">Shares exclude transplants with an unknown distance (none in these periods). Kidney is kidney alone.</p>`;
  const labels = ORGANS.flatMap((o) => [`${cap(o)} · ${d.prior_label}`, `${cap(o)} · ${d.current_label}`]);
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
function renderNews(news) {
  $("news-updated").textContent = news.fetched_at ? `Fetched ${fmtDate(news.fetched_at)} · last ${news.lookback_days} days` : "Awaiting first fetch";
  const items = news.items || [];
  const groups = news.groups || [];
  const labels = Object.fromEntries(groups.map((g) => [g.id, g.label]));
  let filter = "all", shown = NEWS_PAGE;
  const filters = $("news-filters");
  filters.innerHTML = [{ id: "all", label: "All" }, ...groups].map((g) => {
    const n = g.id === "all" ? items.length : items.filter((i) => i.tags.includes(g.id)).length;
    return `<button data-f="${g.id}" aria-pressed="${g.id === "all"}">${esc(g.label)} (${n})</button>`;
  }).join("");
  const draw = () => {
    const list = items.filter((i) => filter === "all" || i.tags.includes(filter));
    $("news-list").innerHTML = list.length ? list.slice(0, shown).map((i) => `<li>
      <a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.headline)}</a>
      <div class="news-meta">${esc(i.source)} · ${fmtDate(i.date)} ${i.tags.map((t) => `<span class="chip">${esc(labels[t] || t)}</span>`).join("")}</div>
    </li>`).join("") : `<li class="awaiting">No items in this category in the last ${news.lookback_days || 90} days.</li>`;
    $("news-more").hidden = list.length <= shown;
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

// ---------- footer ----------
function renderSources(files) {
  const rows = [
    ["SRTA share price", files.price, "price"],
    ["Weekly transplant volumes", files.transplants_weekly, "transplants_weekly"],
    ["Deceased donors recovered + discard rate", files.donors_weekly, "donors_weekly"],
    ["Donor mix (DBD / DCD)", files.donor_mix, "donor_mix"],
    ["Distance bands", files.distance, "distance"],
    ["Weekly transplants by OPTN region", files.regions_weekly, "regions_weekly"],
    ["Transplants by state (monthly snapshots)", files.location, "location"],
    ["News & company mentions", files.news, "news"],
  ];
  $("sources-body").innerHTML = rows.map(([name, f, key]) => {
    const tag = f.tag || "—";
    return `<tr><td>${name}</td><td>${esc(f.source || "n/a")}</td><td><span class="tier-tag ${tag.toLowerCase()}">${esc(tag)}</span></td><td>${CADENCE[key]}</td></tr>`;
  }).join("") + `<tr><td>Organ-miles</td><td><a href="https://slogatskiy.github.io/srta-organ-miles-tracker/" target="_blank" rel="noopener">SRTA organ-miles tracker</a></td><td><span class="tier-tag linked">Linked</span></td><td>Maintained externally</td></tr>`;
}

(async function main() {
  const [summary, tw, dw, mix, dist, loc, rw, news, price] = await Promise.all([
    load("data/weekly_summary.json"),
    load("data/processed/transplants_weekly.json"),
    load("data/processed/donors_weekly.json"),
    load("data/processed/donor_mix.json"),
    load("data/processed/distance.json"),
    load("data/processed/location.json"),
    load("data/processed/regions_weekly.json"),
    load("data/processed/news.json"),
    load("data/processed/price.json"),
  ]);
  renderHeader(summary, price);
  renderVolumes(summary, tw);
  renderDonorLine(summary, dw);
  renderDonorMix(mix);
  renderDistance(dist);
  renderRegions(summary, rw);
  renderLocation(loc);
  renderNews(news);
  renderSources({ price, transplants_weekly: tw, donors_weekly: dw, donor_mix: mix, distance: dist, regions_weekly: rw, location: loc, news });
})();
