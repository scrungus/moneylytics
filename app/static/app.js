const $ = (s) => document.querySelector(s);
const gbp = (v) => new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 }).format(v);
const gbp2 = (v) => new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(v);
const api = async (path) => { const r = await fetch(path); if (!r.ok) throw new Error(await r.text()); return r.json(); };

const PALETTE = ["#5eead4", "#60a5fa", "#f472b6", "#facc15", "#fb923c", "#a78bfa", "#4ade80", "#f87171", "#38bdf8", "#e879f9", "#fbbf24", "#34d399", "#c084fc", "#fda4af"];
const CHART_BASE = { backgroundColor: "transparent", textStyle: { color: "#e6e8ee" } };

let META = { months: [], categories: [] };
const charts = {};
const loaded = {};

function mkChart(id) {
  if (!charts[id]) charts[id] = echarts.init(document.getElementById(id), null, { renderer: "canvas" });
  return charts[id];
}
window.addEventListener("resize", () => Object.values(charts).forEach((c) => c.resize()));

/* ---------- tabs ---------- */
document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("nav button, .tab").forEach((el) => el.classList.remove("active"));
    b.classList.add("active");
    $(`#tab-${b.dataset.tab}`).classList.add("active");
    loadTab(b.dataset.tab);
    Object.values(charts).forEach((c) => c.resize());
  })
);

function loadTab(name, force = false) {
  if (loaded[name] && !force) return;
  loaded[name] = true;
  ({ overview: loadOverview, categories: loadCategories, merchants: loadMerchants,
     subscriptions: loadSubscriptions, transactions: loadTransactions, insights: initInsights }[name])();
}

/* ---------- overview ---------- */
async function loadOverview() {
  const data = await api("/api/overview?months=13");
  if (!data.length) return;
  const cur = data[data.length - 1], prev = data[data.length - 2] || {};
  const delta = (a, b, invert) => {
    if (b == null || !b) return "";
    const pct = ((a - b) / Math.abs(b)) * 100;
    const cls = (pct > 0) === !invert ? "up" : "down";
    return `<div class="delta ${invert ? (pct > 0 ? "down" : "up") : cls}">${pct > 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(0)}% vs ${prev.month}</div>`;
  };
  $("#cards").innerHTML = `
    <div class="card"><div class="label">Spend — ${cur.month}</div><div class="value">${gbp(cur.spend)}</div>${delta(cur.spend, prev.spend)}</div>
    <div class="card"><div class="label">Income — ${cur.month}</div><div class="value">${gbp(cur.income)}</div>${delta(cur.income, prev.income, true)}</div>
    <div class="card"><div class="label">Net — ${cur.month}</div><div class="value ${cur.net >= 0 ? "pos" : "neg"}">${gbp(cur.net)}</div></div>
    <div class="card"><div class="label">Avg monthly spend (12m)</div><div class="value">${gbp(data.slice(0, -1).reduce((s, m) => s + m.spend, 0) / Math.max(1, data.length - 1))}</div></div>`;
  mkChart("chart-overview").setOption({
    ...CHART_BASE,
    tooltip: { trigger: "axis", valueFormatter: gbp2 },
    legend: { textStyle: { color: "#8b91a3" } },
    grid: { left: 70, right: 20, top: 40, bottom: 30 },
    xAxis: { type: "category", data: data.map((d) => d.month), axisLine: { lineStyle: { color: "#2a2f3d" } } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "#2a2f3d" } } },
    series: [
      { name: "Spend", type: "bar", data: data.map((d) => d.spend), itemStyle: { color: "#f87171", borderRadius: [4, 4, 0, 0] } },
      { name: "Income", type: "bar", data: data.map((d) => d.income), itemStyle: { color: "#4ade80", borderRadius: [4, 4, 0, 0] } },
      { name: "Net", type: "line", data: data.map((d) => d.net), smooth: true, itemStyle: { color: "#5eead4" } },
    ],
  });
}

/* ---------- categories ---------- */
async function loadCategories() {
  const month = $("#cat-month").value || undefined;
  const range = rangeOf("cat");
  const data = await api(`/api/categories?months=13${range
    ? `&date_from=${range.from}&date_to=${range.to}`
    : month ? `&month=${month}` : ""}`);
  const months = Object.keys(data.trend).sort();
  const sel = data.selected;
  const selMonth = data.selected_month;
  if (!$("#cat-month").options.length) fillMonthSelect($("#cat-month"), selMonth);

  const entries = Object.entries(sel).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  mkChart("chart-cat-pie").setOption({
    ...CHART_BASE,
    tooltip: { valueFormatter: gbp2 },
    title: { text: `Spend by category — ${selMonth}`, left: "center", textStyle: { color: "#8b91a3", fontSize: 13 } },
    series: [{ type: "pie", radius: ["45%", "72%"], top: 20,
      data: entries.map(([name, value], i) => ({ name, value, itemStyle: { color: PALETTE[i % PALETTE.length] } })),
      label: { color: "#e6e8ee", formatter: "{b}\n{d}%" } }],
  });

  const allCats = [...new Set(months.flatMap((m) => Object.keys(data.trend[m])))];
  const topCats = allCats.map((c) => [c, months.reduce((s, m) => s + (data.trend[m][c] || 0), 0)])
    .sort((a, b) => b[1] - a[1]).slice(0, 8).map(([c]) => c);
  mkChart("chart-cat-trend").setOption({
    ...CHART_BASE,
    tooltip: { trigger: "axis", valueFormatter: gbp2 },
    legend: { textStyle: { color: "#8b91a3" }, type: "scroll" },
    grid: { left: 60, right: 20, top: 60, bottom: 30 },
    xAxis: { type: "category", data: months },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "#2a2f3d" } } },
    series: topCats.map((c, i) => ({ name: c, type: "bar", stack: "s",
      data: months.map((m) => data.trend[m][c] || 0), itemStyle: { color: PALETTE[i % PALETTE.length] } })),
  });

  const idx = months.indexOf(selMonth);
  const prevMonth = idx > 0 ? months[idx - 1] : null;
  const prev = prevMonth ? data.trend[prevMonth] : {};
  $("#cat-table tbody").innerHTML = entries.map(([c, v]) => {
    const p = prev[c] || 0;
    const d = p ? (((v - p) / p) * 100).toFixed(0) : null;
    return `<tr><td>${c}</td><td class="num">${gbp2(v)}</td><td class="num">${p ? gbp2(p) : "—"}</td>
      <td class="num ${d > 0 ? "up" : "down"}">${d != null ? (d > 0 ? "+" : "") + d + "%" : "—"}</td></tr>`;
  }).join("");
}
$("#cat-month").addEventListener("change", loadCategories);

/* ---------- merchants ---------- */
async function loadMerchants() {
  if (!$("#mer-month").options.length) {
    fillMonthSelect($("#mer-month"), META.months[META.months.length - 1], true);
    META.categories.filter((c) => !["Income", "Excluded"].includes(c))
      .forEach((c) => $("#mer-category").insertAdjacentHTML("beforeend", `<option>${c}</option>`));
  }
  const m = $("#mer-month").value, c = $("#mer-category").value;
  const range = rangeOf("mer");
  const data = await api(`/api/merchants?limit=25${range
    ? `&date_from=${range.from}&date_to=${range.to}`
    : m ? `&month=${m}` : ""}${c ? `&category=${encodeURIComponent(c)}` : ""}`);
  const rows = data.slice().reverse();
  mkChart("chart-merchants").setOption({
    ...CHART_BASE,
    tooltip: { valueFormatter: gbp2, trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 170, right: 40, top: 20, bottom: 30 },
    xAxis: { type: "value", splitLine: { lineStyle: { color: "#2a2f3d" } } },
    yAxis: { type: "category", data: rows.map((r) => r.merchant), axisLabel: { color: "#e6e8ee", width: 150, overflow: "truncate" } },
    series: [{ type: "bar", data: rows.map((r) => r.spend), itemStyle: { color: "#60a5fa", borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: "#8b91a3", formatter: (p) => gbp(p.value) } }],
  });
}
$("#mer-month").addEventListener("change", loadMerchants);
$("#mer-category").addEventListener("change", loadMerchants);

/* ---------- subscriptions ---------- */
async function loadSubscriptions() {
  const subs = await api("/api/subscriptions");
  const active = subs.filter((s) => s.active);
  const monthly = active.reduce((s, x) => s + x.monthly_cost, 0);
  $("#sub-summary").innerHTML = `
    <div class="card"><div class="label">Active recurring</div><div class="value">${active.length}</div></div>
    <div class="card"><div class="label">Monthly cost</div><div class="value">${gbp2(monthly)}</div></div>
    <div class="card"><div class="label">Yearly cost</div><div class="value">${gbp(monthly * 12)}</div></div>`;
  $("#sub-table tbody").innerHTML = subs.map((s) => `
    <tr><td>${s.merchant}</td><td class="num">${gbp2(s.amount)}</td><td>${s.cadence}</td>
    <td class="num">${gbp2(s.monthly_cost)}</td><td class="num">${s.count}×</td><td>${s.last_paid}</td>
    <td><span class="badge ${s.active ? "" : "inactive"}">${s.active ? "active" : "lapsed"}</span></td></tr>`).join("");
}

/* ---------- transactions ---------- */
let txOffset = 0;
async function loadTransactions(append = false) {
  if (!$("#tx-month").options.length || $("#tx-month").options.length === 1) {
    META.months.slice().reverse().forEach((m) => $("#tx-month").insertAdjacentHTML("beforeend", `<option>${m}</option>`));
    META.categories.forEach((c) => $("#tx-category").insertAdjacentHTML("beforeend", `<option>${c}</option>`));
  }
  if (!append) txOffset = 0;
  const p = new URLSearchParams({ limit: 100, offset: txOffset });
  const range = rangeOf("tx");
  if (range) { p.set("date_from", range.from); p.set("date_to", range.to); }
  else if ($("#tx-month").value) p.set("month", $("#tx-month").value);
  if ($("#tx-category").value) p.set("category", $("#tx-category").value);
  if ($("#tx-search").value) p.set("q", $("#tx-search").value);
  const data = await api(`/api/transactions?${p}`);
  const opts = (sel) => META.categories.map((c) => `<option ${c === sel ? "selected" : ""}>${c}</option>`).join("");
  const html = data.items.map((t) => `
    <tr><td>${t.date}</td><td title="${t.notes || ""}">${t.display_name || t.merchant}</td>
    <td class="num ${t.amount < 0 ? "" : "pos"}">${gbp2(t.amount)}</td>
    <td><select class="${t.overridden ? "overridden" : ""}" data-id="${t.id}">${opts(t.category)}</select></td>
    <td class="muted">${t.account}</td></tr>`).join("");
  if (append) $("#tx-table tbody").insertAdjacentHTML("beforeend", html);
  else $("#tx-table tbody").innerHTML = html;
  txOffset += data.items.length;
  $("#tx-count").textContent = `${txOffset} of ${data.total}`;
  $("#tx-more").style.display = txOffset < data.total ? "" : "none";
}
["#tx-month", "#tx-category"].forEach((s) => $(s).addEventListener("change", () => loadTransactions()));
let searchTimer;
$("#tx-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadTransactions(), 350); });
$("#tx-more").addEventListener("click", () => loadTransactions(true));
$("#tx-table").addEventListener("change", async (e) => {
  if (e.target.tagName !== "SELECT") return;
  const applyAll = confirm(`Apply "${e.target.value}" to ALL transactions from this merchant?\nOK = all, Cancel = just this one.`);
  await fetch(`/api/transactions/${e.target.dataset.id}/category`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category: e.target.value, apply_to_merchant: applyAll }),
  });
  e.target.classList.add("overridden");
});

/* ---------- insights ---------- */
function initInsights() {
  if (!$("#ins-month").options.length) fillMonthSelect($("#ins-month"), META.months[META.months.length - 1]);
  loadInsight(false);
}
async function loadInsight(refresh) {
  const month = $("#ins-month").value;
  const btn = $("#ins-generate");
  if (refresh) { btn.disabled = true; btn.textContent = "Generating… (~30s)"; }
  $("#ins-content").innerHTML = `<p class="muted">${refresh ? "Claude is reading your month… this takes about 30 seconds." : "Loading…"}</p>`;
  try {
    const data = await api(`/api/insights/${month}${refresh ? "?refresh=1" : ""}`);
    if (data.content) $("#ins-content").innerHTML = marked.parse(data.content);
    else if (!refresh) $("#ins-content").innerHTML = `<p class="muted">No digest for ${month} yet — hit Generate.</p>`;
    else $("#ins-content").innerHTML = `<p class="muted">${data.error || "Failed"}</p>`;
  } catch (e) { $("#ins-content").innerHTML = `<p class="muted">Error: ${e.message}</p>`; }
  finally { btn.disabled = false; btn.textContent = "Generate"; }
}
$("#ins-generate").addEventListener("click", () => loadInsight(true));
$("#ins-month").addEventListener("change", () => loadInsight(false));

/* ---------- shared ---------- */
function fillMonthSelect(sel, selected, withAll = false) {
  sel.innerHTML = withAll ? `<option value="">All months</option>` : "";
  META.months.slice().reverse().forEach((m) =>
    sel.insertAdjacentHTML("beforeend", `<option ${m === selected ? "selected" : ""}>${m}</option>`));
}

// ◀ ▶ steppers around a month <select>. Options are newest-first, so
// "back" (older) moves the index forward and vice versa.
function addMonthArrows(selectId) {
  const sel = document.getElementById(selectId);
  const step = (dir) => {
    if (sel.disabled) return; // a custom range is active
    const opts = [...sel.options];
    let i = sel.selectedIndex + dir;
    if (opts[i] && opts[i].value === "") i += dir; // skip "All months"
    if (i < 0 || i >= opts.length) return;
    sel.selectedIndex = i;
    sel.dispatchEvent(new Event("change"));
  };
  const back = document.createElement("button");
  back.textContent = "◀"; back.className = "arrow"; back.title = "Previous month";
  back.addEventListener("click", () => step(1));
  const fwd = document.createElement("button");
  fwd.textContent = "▶"; fwd.className = "arrow"; fwd.title = "Next month";
  fwd.addEventListener("click", () => step(-1));
  sel.before(back);
  sel.after(fwd);
}
["cat-month", "mer-month", "tx-month", "ins-month"].forEach(addMonthArrows);

// custom date range: when both dates are set it overrides the month select
function rangeOf(prefix) {
  const from = $(`#${prefix}-from`).value, to = $(`#${prefix}-to`).value;
  return from && to ? { from, to } : null;
}
function wireRange(prefix, reload) {
  const sync = () => {
    const active = !!rangeOf(prefix);
    $(`#${prefix}-month`).disabled = active;
    reload();
  };
  $(`#${prefix}-from`).addEventListener("change", sync);
  $(`#${prefix}-to`).addEventListener("change", sync);
  $(`#${prefix}-clear`).addEventListener("click", () => {
    $(`#${prefix}-from`).value = ""; $(`#${prefix}-to`).value = "";
    $(`#${prefix}-month`).disabled = false;
    reload();
  });
}
wireRange("cat", () => loadCategories());
wireRange("mer", () => loadMerchants());
wireRange("tx", () => loadTransactions());

$("#refresh-btn").addEventListener("click", async () => {
  $("#refresh-btn").classList.add("spinning");
  try { await fetch("/api/refresh", { method: "POST" }); } finally {
    $("#refresh-btn").classList.remove("spinning");
    Object.keys(loaded).forEach((k) => delete loaded[k]);
    await boot();
  }
});

async function boot() {
  META = await api("/api/meta");
  $("#last-sync").textContent = META.last_sync
    ? `synced ${new Date(META.last_sync).toLocaleTimeString()} · ${META.transaction_count} txs`
    : "never synced";
  const activeTab = document.querySelector("nav button.active").dataset.tab;
  loadTab(activeTab, true);
}
boot();
