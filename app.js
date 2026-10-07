// SRTA Transplant Tracker — renders everything from data/*.json. No numbers live in this file.
const ORGANS = ["heart", "liver", "lung", "kidney"];
const CADENCE = {
  price: "Weekly (Sun) via GitHub Action",
  news: "Weekly (Sun) via GitHub Action; 90-day window",
  transplants_weekly: "When a new OPTN export is dropped in",
  donor_mix: "When a new OPTN export is dropped in",
  distance: "When a new OPTN export is dropped in",
  location: "When a new OPTN export is dropped in",
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
  ul.innerHTML = (summary.bullets || []).map((b) => `<li>${esc(b)}</li>`).join("") || "<li>Digest not generated yet.</li>";
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
  const rows = currentOrgan === "all" ? totalSeries(tw.organs || {}) : (tw.organs || {})[currentOrgan] || [];
  const byYear = {};
  rows.forEach((r) => {
    const { year, week } = isoWeek(r.week_start);
    (byYear[year] = byYear[year] || {})[week] = r.count;
  });
  const years = Object.keys(byYear).map(Number).sort((a, b) => b - a).slice(0, 3);
  const colors = [css("--yr0"), css("--yr1"), css("--yr2")];
  const labels = Array.from({ length: 53 }, (_, i) => i + 1);
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
        x: { title: { display: true, text: "ISO week", color: css("--muted") }, ticks: { color: css("--muted"), maxTicksLimit: 14 }, grid: { display: false } },
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
    ? `OPTN pull ${fmtDate(tw.data_as_of)} · ${tw.raw_file}` : "Awaiting first OPTN file";
  renderCards(summary, tw);
  $("organ-tabs").innerHTML = [...ORGANS, "all"].map((o) =>
    `<button role="tab" data-organ="${o}" aria-selected="${o === currentOrgan}">${o === "all" ? "All organs" : cap(o)}</button>`).join("");
  $("organ-tabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => selectOrgan(b.dataset.organ, tw)));
  drawVolumes(tw);
}

// ---------- donor mix / distance / location (normalized schemas, see README) ----------
function updatedLabel(d) {
  return d.status === "ok" ? `OPTN pull ${fmtDate(d.data_as_of)}` : "Awaiting first OPTN file";
}

function renderDonorMix(d) {
  $("mix-updated").textContent = updatedLabel(d);
  if (d.status !== "ok") { $("mix-body").innerHTML = awaiting("DBD vs. DCD donor counts and DCD share by organ", "an OPTN national-data export"); return; }
  const donors = d.donors || [];
  let html = `<div class="scroll-x"><table><thead><tr><th>Period</th><th>DBD donors</th><th>DCD donors</th><th>DCD share</th></tr></thead><tbody>${
    donors.slice().reverse().map((r) => `<tr><td>${esc(r.period)}</td><td>${fmtInt(r.dbd)}</td><td>${fmtInt(r.dcd)}</td><td>${(100 * r.dcd / (r.dbd + r.dcd)).toFixed(1)}%</td></tr>`).join("")
  }</tbody></table></div>`;
  const share = d.dcd_share_by_organ || {};
  const organs = ORGANS.filter((o) => (share[o] || []).length);
  if (organs.length) {
    html += `<h3 class="note">DCD share of transplants by organ (latest period)</h3><div class="scroll-x"><table><thead><tr><th>Organ</th><th>Period</th><th>DCD</th><th>Total</th><th>DCD share</th></tr></thead><tbody>${
      organs.map((o) => { const r = share[o][share[o].length - 1]; return `<tr><td>${cap(o)}</td><td>${esc(r.period)}</td><td>${fmtInt(r.dcd)}</td><td>${fmtInt(r.total)}</td><td>${(100 * r.dcd / r.total).toFixed(1)}%</td></tr>`; }).join("")
    }</tbody></table></div>`;
  }
  $("mix-body").innerHTML = html;
}

function renderDistance(d, summary) {
  $("dist-updated").textContent = updatedLabel(d);
  if (d.status !== "ok") { $("dist-body").innerHTML = awaiting("Distance-band shares by organ", "an OPTN distance export"); return; }
  const bands = d.band_order || [];
  const rows = ORGANS.filter((o) => (d.organs || {})[o]?.length).map((o) => {
    const p = d.organs[o][d.organs[o].length - 1];
    const tot = bands.reduce((s, b) => s + (p.bands[b] || 0), 0);
    const ch = ((summary.distance || {}).organs || {})[o] || {};
    return `<tr><td>${cap(o)}</td><td>${esc(p.period)}</td>${bands.map((b) => `<td>${tot ? (100 * (p.bands[b] || 0) / tot).toFixed(1) + "%" : "n/a"}</td>`).join("")}<td>${ch.change_pts == null ? "n/a" : (ch.change_pts > 0 ? `<span class="up">▲ ${ch.change_pts} pts</span>` : ch.change_pts < 0 ? `<span class="down">▼ ${Math.abs(ch.change_pts)} pts</span>` : "— 0 pts")}</td></tr>`;
  }).join("");
  $("dist-body").innerHTML = `<div class="scroll-x"><table><thead><tr><th>Organ</th><th>Period</th>${bands.map((b) => `<th>${esc(b)} NM</th>`).join("")}<th>Long-band share vs LY</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderLocation(d) {
  $("loc-updated").textContent = updatedLabel(d);
  if (d.status !== "ok") { $("loc-body").innerHTML = awaiting("Transplants by transplant-center state or OPTN region", "an OPTN state/regional export"); return; }
  const rows = (d.rows || []).slice().sort((a, b) => b.latest - a.latest);
  $("loc-body").innerHTML = `<p class="note">${esc(d.latest_period)} vs ${esc(d.prior_period)}, by ${esc(d.level || "area")}.</p><div class="scroll-x"><table><thead><tr><th>${cap(d.level || "Area")}</th><th>Latest</th><th>Prior year</th><th>YoY</th></tr></thead><tbody>${
    rows.map((r) => `<tr><td>${esc(r.area)}</td><td>${fmtInt(r.latest)}</td><td>${fmtInt(r.prior)}</td><td>${yoy(r.prior ? Math.round(1000 * (r.latest / r.prior - 1)) / 10 : null)}</td></tr>`).join("")
  }</tbody></table></div>`;
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
    ["Donor mix (DBD / DCD)", files.donor_mix, "donor_mix"],
    ["Distance bands", files.distance, "distance"],
    ["Transplants by state / region", files.location, "location"],
    ["News & company mentions", files.news, "news"],
  ];
  $("sources-body").innerHTML = rows.map(([name, f, key]) => {
    const tag = f.tag || "—";
    return `<tr><td>${name}</td><td>${esc(f.source || "n/a")}</td><td><span class="tier-tag ${tag.toLowerCase()}">${esc(tag)}</span></td><td>${CADENCE[key]}</td></tr>`;
  }).join("") + `<tr><td>Organ-miles</td><td><a href="https://slogatskiy.github.io/srta-organ-miles-tracker/" target="_blank" rel="noopener">SRTA organ-miles tracker</a></td><td><span class="tier-tag linked">Linked</span></td><td>Maintained externally</td></tr>`;
}

(async function main() {
  const [summary, tw, mix, dist, loc, news, price] = await Promise.all([
    load("data/weekly_summary.json"),
    load("data/processed/transplants_weekly.json"),
    load("data/processed/donor_mix.json"),
    load("data/processed/distance.json"),
    load("data/processed/location.json"),
    load("data/processed/news.json"),
    load("data/processed/price.json"),
  ]);
  renderHeader(summary, price);
  renderVolumes(summary, tw);
  renderDonorMix(mix);
  renderDistance(dist, summary);
  renderLocation(loc);
  renderNews(news);
  renderSources({ price, transplants_weekly: tw, donor_mix: mix, distance: dist, location: loc, news });
})();
