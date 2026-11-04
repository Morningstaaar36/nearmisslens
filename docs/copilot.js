// NearMissLens copilot. One page for the static site (precomputed reports in data/) and the live server (the same
// data/ paths, plus POST engineer and letter for corners that are not precomputed).
"use strict";
const meta = n => (document.querySelector(`meta[name="${n}"]`) || {}).content || "";
const MODE = meta("nml-mode") === "live" ? "live" : "static";
const LIVE = MODE === "live" ? "" : (meta("nml-live").startsWith("https://") ? meta("nml-live").replace(/\/?$/, "/") : null);
const REPO = meta("nml-repo").startsWith("https://") ? meta("nml-repo") : "";
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const safeUrl = u => /^https?:\/\//i.test(String(u ?? "")) ? esc(u) : "#";  // never a javascript: or data: link
const usd = v => v == null ? "n/a" : v >= 1e8 ? `$${Math.round(v / 1e6)} million` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)} million` : `$${Math.round(v).toLocaleString("en-US")}`;
const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];
const pct = v => `${Math.round(100 * v)}%`;
const date = s => s ? new Date(s + "T12:00:00").toLocaleDateString("en-GB", {day: "numeric", month: "long", year: "numeric"}) : "";
let INDEX = null, map = null, layer = null, pin = null, mapPlaced = false;  // placed: zoomed to the city or a corner while visible

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  let body = null;
  try { body = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok || !body) throw new Error((body && body.error) || `the server answered ${r.status}`);
  if (body.error) throw new Error(body.error);
  return body;
}

let CITY = null;
const CITY_NAMES = {};  // city id -> name, from the site's own index (a fallback when the live list cannot be reached)
const cityName = id => CITY_NAMES[id] || String(id || "").replace(/^./, ch => ch.toUpperCase());

function route() {
  // "#city/corner", "#corner" (the default city) or "#city"
  const h = decodeURIComponent(location.hash.slice(1)), q = new URLSearchParams(location.search);
  const [a, b] = h.includes("/") ? h.split("/", 2) : [null, h];  // "#city/plan" opens the city's action plan
  return {city: q.get("city") || a, corner: q.get("c") || b};
}

async function boot() {
  let top;
  try { top = await getJSON("data/index.json"); } catch (e) {
    $("citynote").textContent = `The city list did not load (${e.message}).`; return;
  }
  const r = route(), ids = (top.cities || []).map(c => c.id);
  for (const c of top.cities || []) CITY_NAMES[c.id] = c.name;
  CITY = ids.includes(r.city) ? r.city : ids.includes(r.corner) ? r.corner : top.default;
  if (ids.length > 1) {
    $("cityswitch").innerHTML = `<label for="city">City</label> <select id="city">` + top.cities.map(c =>
      `<option value="${esc(c.id)}"${c.id === CITY ? " selected" : ""}>${esc(c.name)} (${c.corners} corners)</option>`).join("") + `</select>`;
    $("city").onchange = e => { location.hash = `${e.target.value}/corners`; location.reload(); };
  }
  try { INDEX = await getJSON(`data/${encodeURIComponent(CITY)}/index.json`); } catch (e) {
    $("citynote").textContent = `The corner list did not load (${e.message}).`; return;
  }
  const s = INDEX.summary || {};
  const kind = INDEX.screen === "crash clusters" ? "corners with the most injury crashes (found from the crash records)" : "priority corners";
  $("citynote").innerHTML = `<b>${INDEX.corners.length}</b> ${esc(INDEX.city_name)} ${kind}, worst first. ` +
    (s.plan_gap != null ? `<span class="gapdot"></span><b>${s.plan_gap}</b> had at least ${INDEX.gap_min_injury_crashes} injury crashes and no recorded safety work in ${INDEX.years} years. ` : "") +
    (s.injury_crashes_distinct ? `The ${Number(s.injury_crashes_distinct).toLocaleString("en-US")} injury crashes within 100 m of them, each counted once, cost about ${usd(s.harm_usd_per_year)} a year. ` : "") +
    `Records as of ${date(INDEX.asof)}.` +
    (INDEX.plan ? ` <button class="quiet planlink" id="planlink">The city's action plan</button>` : "");
  if (INDEX.plan) $("planlink").onclick = () => { location.hash = `${CITY}/plan`; };
  const [sLat, wLon, nLat, eLon] = INDEX.bbox;
  map = L.map("map", {scrollWheelZoom: false}).fitBounds([[sLat, wLon], [nLat, eLon]]);
  const osmTiles = () => L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, attribution: "© OpenStreetMap contributors"});
  let failedTiles = 0;
  // Esri's street basemap first: no key, not a volunteer server with a strict usage policy; OpenStreetMap's own if it fails
  const base = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    {maxZoom: 19, attribution: "Tiles © Esri · Esri, HERE, Garmin, OpenStreetMap contributors"}).addTo(map);
  base.on("tileerror", () => { if (++failedTiles === 4) { map.removeLayer(base); osmTiles().addTo(map); } });
  layer = L.layerGroup().addTo(map);
  const css = getComputedStyle(document.documentElement);
  const red = css.getPropertyValue("--stop").trim(), grey = css.getPropertyValue("--mut").trim();
  for (const c of INDEX.corners) {
    L.circleMarker([c.lat, c.lon], {radius: 3 + Math.sqrt(c.injury_crashes || 0) / 2, color: c.plan_gap ? red : grey,
      weight: 1, fillOpacity: .55}).bindTooltip(`${esc(c.name)}: ${c.injury_crashes} injury crashes`)
      .on("click", () => openCorner(c)).addTo(layer);
  }
  listCorners(INDEX.corners);
  serviceStatus();
  dispatch(r);
  window.addEventListener("hashchange", () => {
    const n = route();
    if (n.city && n.city !== CITY && ids.includes(n.city)) { location.reload(); return; }
    dispatch(n);
  });
}

const VIEWS = {review: () => showReview(), program: () => showProgram(), check: () => showCheck(), desk: () => showDesk(),
  plan: () => showPlan(), corners: () => showCorners()};

function dispatch(r) {
  // one task per screen: the start screen, a task, or a corner's case
  const hit = r.corner && INDEX.corners.find(c => c.slug === r.corner);
  if (VIEWS[r.corner]) VIEWS[r.corner]();
  else if (hit) openCorner(hit);
  else showStart();
}

function setView(name) {
  // which task is open: the task bar marks it, and the map shows only for looking up corners
  const withMap = name === "corners";
  document.body.className = `view-${name}` + (withMap ? " with-map" : "");
  for (const a of document.querySelectorAll("nav.tasks a")) {
    if (a.dataset.view === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  if (withMap && map) setTimeout(() => {
    map.invalidateSize();  // the map was drawn while hidden: size it, and frame the city unless a corner already is
    if (!mapPlaced) { const [sLat, wLon, nLat, eLon] = INDEX.bbox; map.fitBounds([[sLat, wLon], [nLat, eLon]]); mapPlaced = true; }
  }, 60);
  window.scrollTo({top: 0});
}

function showStart() {
  setView("start");
  const card = (href, t, d, k, primary) => `<li><a href="${href}" class="task-${href.slice(1)}${primary ? " primary" : ""}">` +
    `<span class="tsign" aria-hidden="true"></span><span class="t">${t}</span>` +
    `<span class="d">${d}</span><span class="k" data-time="${k}"></span><span class="go">${primary ? "Start here" : "Open"}</span></a></li>`;
  $("out").innerHTML = `<section class="start"><h2>Is this street-safety project worth funding?</h2>` +
    `<p class="lede">Checked against the city's own crash record before money is spent, in <span id="citylist">the covered cities</span>.</p>` +
    flowChart([["you", "Describe a fix and where"], ["model", "Muse Spark reads the corner's crash record"],
               ["code", "Sets the verdict"], ["model", "Muse Spark Open argues against it"],
               ["code", "Keeps only objections that check out"], ["you", "Get a memo with its sources"]]) +
    `<h3 class="ask">What do you want to do?</h3><ul class="cards">` +
    card("#review", "Review a project", "One fix, one corner: fund it or not?", "review", true) +
    card("#program", "Review a list", "Rank many projects within a budget.", "program") +
    card("#check", "Check a claim", "Is what was said about a corner true?", "check") +
    card("#corners", "Look up a corner", `The worst corners in ${esc(INDEX.city_name)}, and who must act.`, "corner") +
    `</ul><div id="sample"></div></section>`;
  sampleResult();
  coveredCities();
  loadDurations().then(fillDurations);
}

function flowChart(nodes) {
  // the path through a task as boxes joined by arrows; each box says who does that part: you, a Meta model, or code
  const who = {you: "You", model: "Meta model", code: "Code"};
  return `<ol class="flow" aria-label="How it works">` + nodes.map(([kind, what]) =>
    `<li class="by-${kind}"><span class="actor">${esc(who[kind])}</span><b>${esc(what)}</b></li>`).join("") + `</ol>`;
}

let SERVER = null;
function serverInfo(fresh) {
  // the live server's cities, limits and service facts, asked once (again when fresh); null when it cannot be reached
  if (!SERVER || fresh) SERVER = LIVE === null ? Promise.resolve(null) : getJSON(`${LIVE}cities`).catch(() => null);
  return SERVER;
}
const refreshStatus = () => { serverInfo(true); serviceStatus(); };

async function serviceStatus() {
  // the task bar says whether live work is possible right now, and the footer says how old the records are
  const d = await serverInfo(), el = $("svc"), svc = (d || {}).service || {};
  if (REPO && $("repolink")) $("repolink").href = REPO;
  const asof = svc.records_as_of || (INDEX || {}).asof;
  if (asof && $("footdate")) $("footdate").textContent = `Records as of ${date(asof)}.`;
  if (!el) return;
  if (LIVE === null) { el.className = "svc"; el.innerHTML = `<i></i>Saved results`; return; }
  if (!d) { el.className = "svc down"; el.innerHTML = `<i></i>Live server not answering: saved results still open`; return; }
  el.className = "svc up";
  el.innerHTML = `<i></i>Live` + (svc.budget_usd != null ? `: $${Number(svc.budget_left_usd).toFixed(2)} of today's $${Number(svc.budget_usd).toFixed(2)} model budget left` : "");
}

async function coveredCities() {
  // the cities this copy can check, from the server (or the site's own index when it cannot be reached)
  let names = [];
  try { names = (await serverInfo()).cities.filter(c => c.checkable).map(c => c.name); } catch (e) { /* below */ }
  if (!names.length) names = Object.values(CITY_NAMES);
  if (names.length && $("citylist")) $("citylist").textContent = names.length > 1 ? names.slice(0, -1).join(", ") + " and " + names.at(-1) : names[0];
}

async function sampleResult() {
  // a real saved review, so a visitor sees what comes back before starting
  let d;
  try { d = await getJSON("data/reviews.json"); } catch (e) { return; }
  const c = (d.cases || []).find(x => x.verdict === "reconsider" && (x.appraisal || {}).in_place) || (d.cases || [])[0];
  if (!c || !$("sample")) return;
  $("sample").innerHTML = `<h3>A real result</h3><p class="legend">Proposal: ${esc(c.input)}</p>` +
    verdictCard(c.verdict, `<p class="legend">Why: ${esc(((c.appraisal || {}).reasons || [])[0] || "")}</p>`) +
    `<p><a href="#review">Review a project of your own</a></p>`;
}

async function showCorners() {
  // look up a corner: the map and the list beside the city's plan (or a prompt to pick one)
  setView("corners");
  if (INDEX.plan) { showPlan(); return; }
  $("out").innerHTML = `<p class="where">${esc(INDEX.city_name)}</p><h2 class="corner">Pick a corner</h2>` +
    `<p class="lede">Choose a corner on the map or in the list, or search one by its street names.</p>`;
}

async function showProgram() {
  // a whole list: each proposal reviewed, then grouped and ranked by code
  setView("program");
  const head = `<p class="where">Review a list</p><h2 class="corner">Which of these projects should be built first?</h2>` +
    steps([`<b>Find</b> the agency's projects on the web, or paste your own`, `<b>We review</b> each one <span data-time="program"></span>`,
           "<b>Read</b> the ranked list and what fits your budget"], 0);
  if (LIVE === null) {
    $("out").innerHTML = head + `<p class="legend">Run your own: <code>nml portfolio list.txt --city CITY --budget-total 500000</code> (see TESTING.md).</p>` + (await savedPrograms());
    return;
  }
  const cities = await liveCities();
  await loadDurations();
  $("out").innerHTML = head + programForm(cities) + (await savedPrograms());
  if (LIMITS.program_items) $("maxitems").textContent = `two to ${LIMITS.program_items}`;
  fillDurations();
  wireProgram();
}

const TIER = {"measured here": "passed the causal gate in this city (estimate uses the smaller national CMF)", "FHWA-cited": "the study FHWA cites", "national studies": "national studies"};

const VERDICT_LABEL = {proceed: "proceed", proceed_after_site_check: "proceed after a site check", compare_alternative: "compare first",
  outside_evidence: "not covered by the evidence", mixed: "decide part by part", reconsider: "reconsider"};
// each verdict as a road sign: guide (go), warning diamond, or the octagon (stop and reconsider), with what it means
const VERDICT_INFO = {
  proceed: {shape: "go", glyph: "✓", label: "Proceed",
    meaning: "The crash record shows the crashes this fix targets, and the evidence for it fits this kind of site.",
    next: "Go ahead with design. The memo says how many injury crashes it is expected to avoid."},
  proceed_after_site_check: {shape: "warn", glyph: "!", label: "Proceed after a site check",
    meaning: "The fix fits, but its estimate assumes something public data cannot show, such as the signal timing or the traffic control.",
    next: "Confirm that condition at the corner, then proceed."},
  compare_alternative: {shape: "warn", glyph: "!", label: "Compare first",
    meaning: "Another proven fix is expected to avoid at least twice as many crashes here.",
    next: "Compare the two before committing money."},
  outside_evidence: {shape: "warn", glyph: "?", label: "Not covered by the evidence",
    meaning: "No federal crash-reduction study fits this fix at this site, so no reduction can be promised.",
    next: "Decide on a site study and an engineer's assessment, or fund a before-and-after study."},
  mixed: {shape: "warn", glyph: "!", label: "Decide part by part",
    meaning: "The parts of this proposal get different verdicts.",
    next: "Read each part's verdict in the table below."},
  reconsider: {shape: "stop", glyph: "✕", label: "Reconsider",
    meaning: "The record or the evidence does not support this fix here as proposed: it may already be installed, or the record shows none of the crashes it targets.",
    next: "Read the reasons before funding it."},
};

function verdictCard(v, extra) {
  const i = VERDICT_INFO[v];
  if (!i) return "";
  return `<div class="vcard ${i.shape}"><div class="vsign ${i.shape}" aria-hidden="true"><span>${i.glyph}</span></div>` +
    `<div class="vtext"><p class="vlabel">${esc(i.label)}</p><p>${esc(i.meaning)}</p>` +
    `<p class="vnext"><b>Next:</b> ${esc(i.next)}</p>${extra || ""}</div></div>`;
}

let DURATIONS = null, LIMITS = {};
async function loadDurations() {
  // how long each task usually takes, from the saved runs' own timings
  if (DURATIONS) return DURATIONS;
  DURATIONS = {};
  try { DURATIONS.review = (await getJSON("data/reviews.json")).summary.mean_seconds; } catch (e) { /* unknown */ }
  try { DURATIONS.check = (await getJSON("data/checks.json")).summary.mean_seconds; } catch (e) { /* unknown */ }
  if (DURATIONS.review) DURATIONS.program = DURATIONS.review * 2;  // reviews run three at a time
  DURATIONS.find = 180;  // live runs on 4 November 2026: two to four minutes
  return DURATIONS;
}
const minutes = s => !s ? "a few minutes" : s < 100 ? "about a minute" : `about ${Math.round(s / 60)} minutes`;
function fillDurations() {
  for (const el of document.querySelectorAll("[data-time]")) {
    const k = el.dataset.time;
    el.textContent = k === "corner" ? "Saved corners open at once" : `Usually ${minutes((DURATIONS || {})[k])}`;
  }
}
async function liveCities() {
  // the cities the server can check, and its limits; the site's own index when it cannot be reached
  let cities = [];
  try {
    const d = await serverInfo();
    cities = (d.cities || []).filter(c => c.checkable);
    LIMITS = d.limits || {};
  } catch (e) { /* below */ }
  if (!cities.length) cities = Object.entries(CITY_NAMES).map(([id, name]) => ({id, name}));
  return cities;
}

function verdictLegend() {
  // the answers a review can give, as the signs the result will show
  return `<details class="vlegend"><summary>What the verdicts mean</summary><ul>` + Object.values(VERDICT_INFO).map(i =>
    `<li><span class="vsign mini ${i.shape}" aria-hidden="true"><span>${i.glyph}</span></span><span><b>${esc(i.label)}</b>: ${esc(i.meaning)}</span></li>`).join("") +
    `</ul></details>`;
}

function steps(items, now) {
  // the task as three boxes joined by arrows: what you do, what happens, what you get; markStep moves it along
  return `<ol class="steps">` + items.map((t, k) => `<li${k === now ? ' aria-current="step"' : ""}><span>${t}</span></li>`).join("") + `</ol>`;
}

function markStep(n) {
  const items = document.querySelectorAll("ol.steps li");
  items.forEach((li, k) => {
    li.classList.toggle("done", k < n);
    if (k === n) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
  });
}
const finished = () => { markStep(2); refreshStatus(); };

const STAGES = {
  review: ["Reads your proposal and matches each part to the federal list of proven fixes",
           "Finds the intersection and its police crash records (the corner's own crashes)",
           "Checks the city's past safety programs and the evidence for each fix",
           "Code sets the verdict",
           "A second model argues against the verdict; code keeps only objections whose facts check out",
           "Writes the memo, which must answer every objection"],
  check: ["Reads the source you gave", "Finds the intersection it names", "Pulls that corner's crash record",
          "Tests every number and every quote", "Writes the case, or says why it cannot"],
  find: ["Muse Spark searches the web for the agency's own pages", "Opens the most promising pages and copies a passage from each",
         "Code opens every page itself: the passage must be on it word for word", "Reads each kept page's intersection projects; code checks each one"],
  program: ["Reviews each project like a single review, three at a time", "Groups them by verdict",
            "Ranks the supported ones by crashes avoided per dollar and fits your budget"],
};

function working(kind, secs, step = 1) {
  // one line for what is happening now and a bar against the usual time; the strip above moves to its second box
  if (step != null) markStep(step);
  const usual = (DURATIONS || {})[kind] || 120, list = STAGES[kind], t = secs || 0;
  const now = list[Math.min(list.length - 1, Math.floor(t / (usual / list.length)))];
  return `<div class="working" role="status" aria-live="polite"><div class="bar" aria-hidden="true"><i style="width:${Math.min(95, 4 + 100 * t / usual).toFixed(0)}%"></i></div>` +
    `<p><span class="spin" aria-hidden="true"></span><b>${Math.round(t)} s</b> · ${esc(now)}</p>` +
    `<p class="legend">Usually ${minutes(usual)}. Keep this page open; the result appears here.</p></div>`;
}

const VERDICT_CLASS = {proceed: "ok", proceed_after_site_check: "warn", compare_alternative: "warn", outside_evidence: "warn", mixed: "warn", reconsider: "bad"};

function reviewResult(r) {
  // a decision memo: the verdict code set, why, the findings with receipts, the red team's checked objections and the answers
  if (r.status !== "published") return `<p class="legend"><b>${esc(r.status)}</b>: ${esc(r.reason || "")}</p>`;
  const a = r.appraisal || {}, m = r.memo || {}, ans = {};
  for (const x of m.answers || []) ans[x.objection] = x;
  const cost = r.cost_usd || {};
  const objs = r.objections || [], parts = a.parts || [];
  const partsTable = parts.length > 1 ? `<table><tr><th>Part</th><th>Verdict</th></tr>${parts.map(x =>
      `<tr><td>${esc(x.countermeasure === "other" ? x.what : x.countermeasure)}</td><td>${esc(x.verdict_text)}</td></tr>`).join("")}</table>` : "";
  const opts = [];
  for (const x of parts.length ? parts : [a]) {
    const pr = x.proposed, alt = x.best_alternative;
    const sign = (VERDICT_INFO[x.verdict] || {}).shape;
    if (pr) opts.push({label: `Proposed: ${esc(pr.countermeasure)}`, value: pr.injury_crashes_avoided_per_year, track: pr.target_crashes_per_year, sign,
                       note: `of ${pr.target_crashes_per_year} ${esc(pr.targets)} a year`});
    if (alt && (!pr || alt.countermeasure !== pr.countermeasure))
      opts.push({label: `Alternative: ${esc(alt.countermeasure)}`, value: alt.injury_crashes_avoided_per_year, track: alt.target_crashes_per_year,
                 note: `of ${alt.target_crashes_per_year} ${esc(alt.targets)} a year`});
  }
  const chart = opts.length ? `<div class="chart"><h4>Injury crashes each option is expected to avoid a year</h4>` +
    `<p class="legend">The light rail is the crashes the fix targets here; the bar is the share the study behind it expects to avoid.</p>${hbars(opts, "injury crashes avoided a year")}</div>` : "";
  return verdictCard(r.verdict, "") + chart +
    `<div class="why3"><h4>Why</h4><ul>${(a.reasons || []).slice(0, 3).map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` +
    `<p class="chips"><span class="chip">Verdict set by code, not the model</span>` +
    (objs.length ? `<span class="chip">${objs.length} objection${objs.length > 1 ? "s" : ""} checked and answered</span>` : "") +
    `<span class="chip">${(m.findings || []).length} findings, each with its source</span></p>` +
    (r.verdict === "mixed" ? partsTable : "") +
    `<details class="more"><summary>The memo</summary><p>${esc(m.summary || "")}</p>` +
    `<ul>${(m.findings || []).map(f => `<li>${esc(f.text)} <span class="legend">[${esc(f.receipt)}]</span></li>`).join("")}</ul>` +
    (r.verdict !== "mixed" ? partsTable : "") + `</details>` +
    (objs.length ? `<details class="more"><summary>The case against this verdict (${objs.length})</summary>` +
      `<p class="legend">Muse Spark Open argued against the verdict. Code kept an objection only if its fact is in the record.</p><ul>` +
      objs.map(o => `<li><b>${esc(o.id)}</b> ${esc(o.objection)} <span class="legend">[${esc(o.receipt)}: ${esc(o.field)} = ${esc(String(o.value))}]</span>` +
        (ans[o.id] ? `<br><i>Answer:</i> ${esc(ans[o.id].answer)} <span class="legend">[${esc(ans[o.id].receipt)}]</span>` : "") + `</li>`).join("") + `</ul></details>` : "") +
    (r.letter ? `<details class="more"><summary>Draft work order (number-checked; nothing is sent)</summary><pre class="letter">${esc(r.letter)}</pre></details>` : "") +
    `<p class="legend">Records as of ${esc(r.asof || "")} · $${esc(cost.meta)} Meta API + $${esc(cost.open_weights_red_team)} Muse Spark Open · ${Math.round(r.seconds || 0)} s</p>`;
}

async function savedReviews() {
  let d;
  try { d = await getJSON("data/reviews.json"); } catch (e) { return ""; }
  const s = d.summary;
  const tryRows = (d.try || []).map(t => `<li>${esc(t.city)}: ${esc(t.proposal)} <span class="legend">(${esc({held_out: "held out: never run by the project", independent: "run by an independent tester", team: "tried by the team"}[t.split] || t.split)}; <a href="${esc(t.source)}" target="_blank" rel="noopener">source</a>)</span></li>`).join("");
  return `<details class="saved"><summary>Reviews already run on real proposals (${(d.cases || []).length})</summary>` +
    `<p class="legend">Registered in ${esc(d.registered)}. ${s.published} of ${s.inputs} memos published; every verdict set by code; ` +
    `${s.objections_kept} red-team objections kept after their facts were checked. Rule ${s.rule_met ? "met" : "not met"}; ` +
    `mean $${Number(s.mean_usd).toFixed(3)} per review.</p>` +
    d.cases.map(c => `<details><summary>${esc(c.city_name || c.city)} · ${esc((c.input || "").slice(0, 90))} · <b>${esc(VERDICT_LABEL[c.verdict] || c.verdict || c.status)}</b></summary>` +
      `<p class="legend">Proposal: ${esc(c.input)} (<a href="${esc(c.source)}" target="_blank" rel="noopener">source</a>)</p>${reviewResult(c)}</details>`).join("") +
    (tryRows ? `<h4>Real proposals to try${LIVE !== null ? " here" : " with nml review"}</h4><ul>${tryRows}</ul>` : "") + `</details>`;
}

async function reviewExamples(cities) {
  // real proposals nobody tuned the tool on (the test set's held-out and team rows): click one to fill the form
  let d;
  try { d = await getJSON("data/reviews.json"); } catch (e) { return; }
  const rows = (d.try || []).slice(0, 3);
  if (!rows.length || !$("reviewin")) return;
  const box = document.createElement("div");
  box.className = "examples";
  box.innerHTML = `<span class="hint">Try a real proposal:</span>` + rows.map((t, i) =>
    `<button type="button" data-i="${i}" title="${esc(t.proposal)}">${esc((cities.find(c => c.id === t.city) || {}).name || cityName(t.city))} · ${esc(t.proposal.slice(0, 44))}${t.proposal.length > 44 ? "…" : ""}</button>`).join("");
  $("reviewin").before(box);
  box.onclick = e => {
    const b = e.target.closest("button[data-i]");
    if (!b) return;
    const t = rows[+b.dataset.i];
    $("reviewin").value = t.proposal;
    if ($("reviewcity")) $("reviewcity").value = t.city;
    $("reviewin").focus();
  };
}

async function checkExamples(cities) {
  // real news links from the saved checks of inputs nobody chose (controls left out): click one to fill the form
  let d;
  try { d = await getJSON("data/checks.json"); } catch (e) { return; }
  const seen = new Set(), rows = (d.cases || []).filter(c => c.kind === "url" && !c.control && c.status === "published" &&
    !seen.has(c.city) && seen.add(c.city)).slice(0, 3);
  if (!rows.length || !$("checkin")) return;
  const box = document.createElement("div");
  box.className = "examples";
  box.innerHTML = `<span class="hint">Try a real news report:</span>` + rows.map((c, i) =>
    `<button type="button" data-i="${i}">${esc((cities.find(x => x.id === c.city) || {}).name || cityName(c.city))}: ` +
    `${esc(new URL(c.input).hostname.replace(/^www\./, ""))}, ${esc((c.corner || "").slice(0, 50))}</button>`).join("");
  $("checkin").before(box);
  box.onclick = e => {
    const b = e.target.closest("button[data-i]");
    if (!b) return;
    const c = rows[+b.dataset.i];
    $("checkin").value = c.input;
    if ($("checkcity")) $("checkcity").value = c.city;
    $("checkin").focus();
  };
}

async function showReview() {
  // Before you commit: a proposed project, reviewed against the city's record before anyone commits money to it
  setView("review");
  const head = `<p class="where">Review a project</p><h2 class="corner">Is this fix worth funding at this corner?</h2>` +
    steps(["<b>Describe</b> the fix, the corner and the cost", `<b>We check</b> the crash record <span data-time="review"></span>`,
           "<b>Read</b> the verdict and the case against it"], 0);
  if (LIVE === null) {
    $("out").innerHTML = head + `<p class="legend">Run your own: <code>nml review "Leading pedestrian intervals at Street A &amp; Street B, about $15,000" --city CITY</code>, ` +
      `or a whole list: <code>nml portfolio list.txt --city CITY --budget-total 500000</code> (see TESTING.md).</p>` +
      (await savedReviews() || `<p class="legend">No saved reviews in this copy.</p>`);
    return;
  }
  const cities = await liveCities();
  await loadDurations();
  $("out").innerHTML = head + `<div class="findrow"><label for="reviewcity">City</label> <select id="reviewcity">${cities.map(c =>
      `<option value="${esc(c.id)}"${c.id === CITY ? " selected" : ""}>${esc(c.name)}</option>`).join("")}</select>` +
    `<button type="button" id="findone" class="quiet">Find a planned project on the web</button></div><div id="findoneout"></div>` +
    `<form id="reviewform" class="search ask"><label class="flabel" for="reviewin">What do you plan to build, and where?</label>` +
    `<textarea id="reviewin" maxlength="1500" rows="3" ` +
    `placeholder="For example: Rapid flashing beacons at Street A &amp; Street B, about $60,000"></textarea>` +
    `<button>Review this project</button></form>` +
    verdictLegend() +
    `<div id="reviewout"></div>` + await savedReviews();
  await reviewExamples(cities);
  fillDurations();
  $("findone").onclick = () => findProjects($("reviewcity").value, $("findone"), $("findoneout"), 1, $("reviewin"));
  $("reviewform").onsubmit = async ev => {
    ev.preventDefault();
    $("reviewout").innerHTML = working("review", 0);
    let job;
    try {
      job = (await getJSON(`${LIVE}review`, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({proposal: $("reviewin").value, city: $("reviewcity").value})})).job;
    } catch (e) { $("reviewout").innerHTML = `<p class="legend">${esc(e.message)}</p>`; return; }
    for (;;) {
      await new Promise(ok => setTimeout(ok, 4000));
      let rec;
      try { rec = await getJSON(`${LIVE}review/${encodeURIComponent(job)}`); }
      catch (e) { $("reviewout").innerHTML = `<p class="legend">${esc(e.message)}</p>`; return; }
      if (rec.status === "running") { $("reviewout").innerHTML = working("review", rec.seconds); continue; }
      if (rec.status === "failed") { $("reviewout").innerHTML = `<p class="legend">${esc(rec.error)}</p>`; return; }
      $("reviewout").innerHTML = reviewResult(rec.result);
      finished();
      return;
    }
  };
}

const PROGRAM_GROUPS = [["build", "Build: the evidence supports these here"], ["site_check", "Build after a site check"],
  ["compare", "Compare first: another proven fix avoids at least twice as many crashes"], ["parts", "Decide part by part"],
  ["study", "Not covered by the evidence: a before-and-after study, not a promise"], ["reconsider", "Reconsider"]];

function programResult(p) {
  // a program review: every proposal reviewed against its own corner, then grouped and ranked by code
  const t = p.totals || {}, money = v => v ? `$${Number(v).toLocaleString("en-US", {maximumFractionDigits: 0})}` : "not given";
  const plan = p.budget_plan;
  return `<p class="legend">${t.proposals} proposals, ${t.reviewed} reviewed. Code ranks them; no model compares one corner with another.` +
    (t.avoided_per_year_if_supported_built ? ` If every supported project is built, the reviews expect about <b>${t.avoided_per_year_if_supported_built}</b> injury crashes avoided a year.` : "") +
    (t.reconsider_cost_usd ? ` Projects to reconsider carry ${money(t.reconsider_cost_usd)} of stated cost.` : "") + `</p>` +
    (plan ? (plan.chosen.length
      ? `<p class="verdict ok"><b>Within ${money(plan.budget_usd)}:</b> fund ${plan.chosen.length} project${plan.chosen.length > 1 ? "s" : ""} ` +
        `for ${money(plan.spent_usd)}, about ${plan.avoided_per_year} injury crashes avoided a year; ${money(plan.left_usd)} left.`
      : `<p class="verdict warn"><b>Within ${money(plan.budget_usd)}:</b> nothing to fund yet. No project in this list has both ` +
        `evidence that it fits its corner and a stated cost.`) +
      (plan.no_cost_given.length ? ` ${plan.no_cost_given.length} supported project${plan.no_cost_given.length > 1 ? "s have" : " has"} no cost to rank.` : "") + `</p>` : "") +
    programChart(p) +
    PROGRAM_GROUPS.filter(([g]) => (p.groups[g] || []).length).map(([g, label]) => `<h4>${esc(label)}</h4><table><tr><th>Proposal</th><th>Avoided a year</th><th>Cost</th><th>Why</th></tr>` +
      p.groups[g].map(x => `<tr><td>${esc(x.input)}</td><td>${x.injury_crashes_avoided_per_year ?? "–"}</td><td>${money(x.cost_usd)}</td>` +
        `<td>${reasonList(x.reasons)}${x.alternative ? `<p class="legend">Alternative: ${esc(x.alternative.countermeasure)}, ${x.alternative.injury_crashes_avoided_per_year} a year</p>` : ""}</td></tr>`).join("") + `</table>`).join("") +
    ((p.not_reviewed || []).length ? `<h4>Not reviewed</h4><ul>${p.not_reviewed.map(x => `<li>${esc(x.input)}: ${esc(x.reason || x.status)}</li>`).join("")}</ul>` : "") +
    `<p class="legend">Cost of the reviews: $${esc(t.review_cost_usd)}.</p>`;
}

function hbars(rows, unit) {
  // horizontal bars on one scale: rows [{label, value, track?, sign?, note?}]; a track is the most the value could be
  // (e.g. the crashes a fix targets), drawn as a light rail behind the bar; the value is written at the bar's end
  const top = Math.max(...rows.map(r => Math.max(r.value || 0, r.track || 0)), 1e-9);
  const w = v => `${(100 * (v || 0) / top).toFixed(1)}%`;
  return `<div class="hb" role="img" aria-label="${esc(unit)}">` + rows.map(r =>
    `<div class="hb-l">${r.sign ? `<span class="vsign mini ${r.sign}" aria-hidden="true"><span>${SIGN_GLYPH[r.sign]}</span></span>` : ""}<span>${r.label}</span></div>` +
    `<div class="hb-c" title="${esc(`${r.value ?? "no estimate"} ${unit}${r.track ? ` of ${r.track} targeted` : ""}`)}">` +
    `<span class="hb-w"><span class="hb-t" style="width:${w(r.track || r.value)}"><span class="hb-f ${r.sign || ""}" style="width:${r.track ? (100 * (r.value || 0) / r.track).toFixed(1) : 100}%"></span></span></span>` +
    `<span class="hb-x"><b class="hb-v">${r.value == null ? "no estimate" : r.value}</b>${r.note ? `<span class="hb-n">${r.note}</span>` : ""}</span></div>`).join("") + `</div>`;
}
const SIGN_GLYPH = {go: "✓", warn: "!", stop: "✕", quiet: "?"};

const GROUP_SIGN = {build: "go", site_check: "warn", compare: "warn", parts: "warn", study: "quiet", reconsider: "stop"};
const GROUP_SHORT = {build: "build", site_check: "build after a site check", compare: "compare first", parts: "decide part by part",
  study: "not covered by the evidence", reconsider: "reconsider"};
function programChart(p) {
  // every proposal on one scale, ranked as code ranked them, each bar wearing its group's sign and name
  const rows = PROGRAM_GROUPS.flatMap(([g]) => (p.groups[g] || []).map(x => ({
    label: esc((x.input || "").replace(/,? as .*$/, "").slice(0, 80)), value: x.injury_crashes_avoided_per_year ?? null,
    sign: GROUP_SIGN[g], note: GROUP_SHORT[g]})));
  return rows.length ? `<div class="chart"><h4>Injury crashes avoided a year, in the order code ranks them</h4>${hbars(rows, "injury crashes avoided a year")}</div>` : "";
}

function cornerGlance(cr, fx, killed, owners) {
  // the corner at a glance: four numbers, then who was hurt as bars on one scale
  if (cr.injury_crashes == null) return "";
  const tiles = `<div class="tiles glance">` +
    `<div class="tile"><b>${cr.injury_crashes}</b><span>injury ${cr.injury_crashes === 1 ? "crash" : "crashes"} in five years</span></div>` +
    `<div class="tile${killed ? " grave" : ""}"><b>${killed}</b><span>${killed === 1 ? "person" : "people"} killed</span></div>` +
    (fx.harm ? `<div class="tile"><b>${usd(fx.harm.usd_per_year)}</b><span>a year in harm (U.S. DOT values)</span></div>` : "") +
    `<div class="tile"><b>${owners}</b><span>road ${owners === 1 ? "owner" : "owners"} who must act</span></div></div>`;
  const hurt = [["Pedestrians", cr.pedestrian_injured], ["Cyclists", cr.cyclist_injured], ["People in vehicles", cr.motorist_injured]]
    .filter(([, v]) => v != null).map(([label, value]) => ({label, value}));
  return tiles + (hurt.length ? `<div class="chart"><h4>Who was hurt</h4>${hbars(hurt, "people injured")}</div>` : "");
}

function reasonList(reasons) {
  // one line per part of a proposal, the fix's name first: "Leading Pedestrian Interval: reconsider: ..."
  return `<ul class="reasons">` + (reasons || []).map(r => {
    const i = r.indexOf(": ");
    return i > 0 && i < 70 ? `<li><b>${esc(r.slice(0, i))}</b>: ${esc(r.slice(i + 2))}</li>` : `<li>${esc(r)}</li>`;
  }).join("") + `</ul>`;
}

async function savedPrograms() {
  let d;
  try { d = await getJSON("data/programs.json"); } catch (e) { return ""; }
  return `<details class="saved"><summary>Lists already reviewed: real agency programs (${(d.programs || []).length})</summary><p class="legend">${esc(d.note || "")}</p>` +
    d.programs.map(p => `<details><summary>${esc(p.city_name || p.city)} · ${esc(p.title)} · ${p.totals.proposals} proposals</summary>` +
      `<p class="legend">Source: <a href="${esc(p.source)}" target="_blank" rel="noopener">${esc(p.agency || "the agency")}</a></p>${programResult(p)}</details>`).join("") + `</details>`;
}

function programForm(cities) {
  // city first; then find the agency's own projects on the web, or paste them; then review
  return `<div class="findrow"><label for="programcity">City</label> <select id="programcity">${cities.map(c =>
      `<option value="${esc(c.id)}"${c.id === CITY ? " selected" : ""}>${esc(c.name)}</option>`).join("")}</select>` +
    `<button type="button" id="findprojects">Find its planned projects on the web</button></div>` +
    `<p class="hint">Muse Spark searches the agency's own pages; code opens each page and checks every project on it.</p><div id="findout"></div>` +
    `<form id="programform" class="search ask"><label class="flabel" for="programin">Projects to review (<span id="maxitems">a few</span>), one per line</label>` +
    `<textarea id="programin" rows="4" ` +
    `placeholder="Rapid flashing beacons at Street A &amp; Street B, $60,000&#10;Curb extensions at Street C &amp; Street D, $40,000"></textarea>` +
    `<label for="programbudget">Budget in dollars (optional)</label> <input id="programbudget" type="number" min="0" step="1000" style="width:9em"> <button>Review the list</button></form>` +
    `<p class="hint">Longer lists (up to 25): <code>nml portfolio --from-url URL --city CITY</code> (see TESTING.md).</p><div id="programout"></div>`;
}

async function findJob(body, box, done) {
  // a web search job: Muse Spark finds pages, code checks each; the panel shows progress, then done(result)
  box.innerHTML = working("find", 0, null);
  let job;
  try {
    job = (await getJSON(`${LIVE}find`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})).job;
  } catch (e) { box.innerHTML = `<p class="legend">${esc(e.message)}</p>`; return; }
  for (;;) {
    await new Promise(ok => setTimeout(ok, 4000));
    let rec;
    try { rec = await getJSON(`${LIVE}find/${encodeURIComponent(job)}`); }
    catch (e) { box.innerHTML = `<p class="legend">${esc(e.message)}</p>`; return; }
    if (rec.status === "running") { box.innerHTML = working("find", rec.seconds, null); continue; }
    if (rec.status === "failed") { box.innerHTML = `<p class="legend">${esc(rec.error)}</p>`; return; }
    done(rec.result);
    return;
  }
}

function foundPages(r) {
  // the pages Muse Spark found on the web, each opened again by code: its passage is on it word for word
  const refused = r.refused || [];
  const tally = `<p class="legend">${(r.searches || []).length} web searches · ${r.pages_read} pages opened · ` +
    `${r.reports.length} kept${(r.read_for_projects || []).length ? ` · ${r.read_for_projects.length} read for projects` : ""}${refused.length ? ` · ${refused.length} refused (${esc([...new Set(refused.map(x => x.why))].join("; "))})` : ""} · $${Number(r.usd || 0).toFixed(2)} of Meta API</p>`;
  const opened = r.opened_not_submitted || [];
  if (!r.reports.length) return (opened.length && (r.read_for_projects || []).length
    ? `<p class="legend">Muse Spark opened these pages but submitted no passage from them, so none is listed as found; ` +
      `their projects were still read and each checked against its page:</p><ul class="webfound">` +
      r.read_for_projects.map(u => `<li><span class="vsign mini warn" aria-hidden="true"><span>!</span></span><div><a href="${safeUrl(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\//, "").slice(0, 90))}</a></div></li>`).join("") + `</ul>`
    : `<p class="legend">No page passed the checks.</p>`) + tally;
  return `<ul class="webfound">` + r.reports.map(x => `<li><span class="vsign mini go" aria-hidden="true"><span>✓</span></span><div>` +
    `<a href="${safeUrl(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>` +
    `<span class="legend"> ${esc(x.publisher)}${x.published ? ", " + esc(x.published) : ""}</span>` +
    `<blockquote>${esc(x.passage)}</blockquote></div></li>`).join("") + `</ul>` + tally;
}

function projectPicker(r, max) {
  // the projects read from the pages: tick the ones to review (the first few are ticked)
  if (!(r.projects || []).length) return `<p class="legend">These pages list no project at a single intersection; paste your own below.</p>`;
  return `<fieldset class="pick"><legend>${r.projects.length} projects at single intersections. ${max === 1 ? "Pick one" : `Pick up to ${max}`}.</legend>` +
    r.projects.map((x, i) => `<label><input type="checkbox" value="${i}"${i < max ? " checked" : ""}>` +
      `<span><b>${esc(x.intersection)}</b> ${esc(x.treatment)}${x.cost_usd ? ` · ${usd(x.cost_usd)}` : ""}</span></label>`).join("") + `</fieldset>`;
}

function findProjects(city, button, box, max, target) {
  // Muse Spark finds the agency's planned projects on the web; ticking one puts it in the text box to review
  button.disabled = true;
  findJob({city}, box, r => {
    box.innerHTML = `<h4>Found on the web</h4>` + foundPages(r) + projectPicker(r, max);
    button.disabled = false;
    const boxes = [...box.querySelectorAll(".pick input")];
    const fill = () => {
      const on = boxes.filter(b => b.checked);
      boxes.forEach(b => { b.disabled = !b.checked && on.length >= max; });
      target.value = on.map(b => r.projects[+b.value].text).join("\n");
    };
    boxes.forEach(b => b.onchange = fill);
    fill();
    box.scrollIntoView({behavior: "smooth", block: "start"});
  });
}

function wireProgram() {
  $("findprojects").onclick = () => findProjects($("programcity").value, $("findprojects"), $("findout"), LIMITS.program_items || 4, $("programin"));
  $("programform").onsubmit = async ev => {
    ev.preventDefault();
    $("programout").innerHTML = working("program", 0);
    const budget = Number($("programbudget").value) || null;
    let job;
    try {
      job = (await getJSON(`${LIVE}portfolio`, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({proposals: $("programin").value, city: $("programcity").value, budget_total: budget})})).job;
    } catch (e) { $("programout").innerHTML = `<p class="legend">${esc(e.message)}</p>`; return; }
    for (;;) {
      await new Promise(ok => setTimeout(ok, 5000));
      let rec;
      try { rec = await getJSON(`${LIVE}portfolio/${encodeURIComponent(job)}`); }
      catch (e) { $("programout").innerHTML = `<p class="legend">${esc(e.message)}</p>`; return; }
      if (rec.status === "running") { $("programout").innerHTML = working("program", rec.seconds); continue; }
      if (rec.status === "failed") { $("programout").innerHTML = `<p class="legend">${esc(rec.error)}</p>`; return; }
      $("programout").innerHTML = programResult(rec.result);
      finished();
      return;
    }
  };
}

async function savedChecks() {
  // the registered run of nml check (T25): inputs fixed before the run, each outcome as the live page shows it
  let d;
  try { d = await getJSON("data/checks.json"); } catch (e) { return ""; }
  const s = d.summary, m = s.met, ok = v => v ? "met" : "not met";
  return `<details class="saved"><summary>Checks already run on real inputs (${(d.cases || []).length})</summary><p class="legend">${s.inputs} inputs fixed before the run (registered test ${esc(d.run)}).</p>` +
    `<p class="legend">Registered in ${esc(d.registered)}. ${s.published_real} of ${s.real} real inputs published (${ok(m.published)}); ` +
    `${s.quotes_verified} of ${s.quotes_published} published quotes found on their page; the off-topic page ${s.offtopic_published ? "was" : "was not"} published ` +
    `and the false zero-crash statement was ${esc(s.false_claim_status)} (${esc((s.false_claim_verdicts || []).join("; ") || "no verdict")}). ` +
    `Rule ${s.rule_met ? "met" : "not met"}; mean $${Number(s.mean_usd).toFixed(3)} of Meta API per input.</p>` +
    d.cases.map(c => `<details><summary>${esc(c.id)}${c.control ? " (control)" : ""} · ${esc(c.city_name || c.city)} · ` +
      `<b>${esc(c.status)}</b>${c.corner ? " · " + esc(c.corner) : ""}</summary>` +
      `<p class="legend">Input (${esc(c.kind)}): ${esc(c.input)}</p>${checkResult(c)}</details>`).join("") + `</details>`;
}

async function showCheck() {
  setView("check");
  // the live desk on your own input: a link, a claim, a source's text or a resident's report, in a registry city
  if (LIVE === null) {
    $("out").innerHTML = `<p class="where">Check a claim · saved results</p><h2 class="corner">Checks of inputs nobody chose for it</h2>` +
      `<p class="lede">Each input went to <code>nml check</code>, the same path as the live page's "Check a claim yourself". ` +
      `Run your own with a Meta key: <code>nml check "a news link or a claim" --city CITY</code> (see TESTING.md).</p>` +
      (await savedChecks() || `<p class="legend">No saved checks in this copy.</p>`);
    return;
  }
  const cities = await liveCities();
  await loadDurations();
  $("out").innerHTML = `<p class="where">Check a claim</p><h2 class="corner">Is what was said about this corner true?</h2>` +
    steps(["<b>Paste</b> a news link or a statement", `<b>We test</b> every number and quote <span data-time="check"></span>`,
           "<b>Read</b> what holds, what differs, what cannot be tested"], 0) +
    `<form id="checkform" class="search ask"><label class="flabel" for="checkin">A news link, or the statement itself</label>` +
    `<textarea id="checkin" maxlength="2000" rows="3" ` +
    `placeholder="https://… a news story, or: The council says this corner had 30 crashes last year"></textarea>` +
    `<label for="checkcity">City</label> <select id="checkcity">${cities.map(c =>
      `<option value="${esc(c.id)}"${c.id === CITY ? " selected" : ""}>${esc(c.name)}</option>`).join("")}</select> ` +
    `<label><input type="checkbox" id="checkreport"> it is a resident's report</label> ` +
    `<input id="checkaddr" maxlength="200" placeholder="where (for a report)"> ` +
    `<input id="checkphoto" maxlength="500" placeholder="photo URL (optional)"> <button>Check</button></form>` +
    `<div id="checkout"></div>` + await savedChecks();
  await checkExamples(cities);
  fillDurations();
  if (!cities.length) { $("checkout").innerHTML = `<p class="legend">No city can be checked on this server.</p>`; return; }
  $("checkform").onsubmit = async ev => {
    ev.preventDefault();
    const report = $("checkreport").checked;
    const body = {input: $("checkin").value, city: $("checkcity").value, kind: report ? "report" : null,
                  address: report ? $("checkaddr").value : null, photo: report ? $("checkphoto").value : null};
    $("checkout").innerHTML = working("check", 0);
    let job;
    try {
      job = (await getJSON(`${LIVE}check`, {method: "POST", headers: {"Content-Type": "application/json"},
                                           body: JSON.stringify(body)})).job;
    } catch (e) { $("checkout").innerHTML = `<p class="legend">${esc(e.message)}</p>`; return; }
    for (;;) {
      await new Promise(r => setTimeout(r, 4000));
      let rec;
      try { rec = await getJSON(`${LIVE}check/${encodeURIComponent(job)}`); }
      catch (e) { $("checkout").innerHTML = `<p class="legend">${esc(e.message)}</p>`; return; }
      if (rec.status === "running") { $("checkout").innerHTML = working("check", rec.seconds); continue; }
      if (rec.status === "failed") { $("checkout").innerHTML = `<p class="legend">${esc(rec.error)}</p>`; return; }
      $("checkout").innerHTML = checkResult(rec.result);
      finished();
      return;
    }
  };
}

function checkResult(r) {
  if (r.status === "unsupported_city" || r.status === "error") return `<p class="legend">${esc(r.reason)}</p>`;
  const head = r.status === "published"
    ? `<div class="vcard go"><div class="vsign go" aria-hidden="true"><span>✓</span></div><div class="vtext"><p class="vlabel">Checked: ${esc(r.corner || "")}</p>` +
      `<p>${esc(r.summary)}</p><p class="vnext"><b>Read:</b> each claim below says whether the record agrees, differs, or cannot test it.</p></div></div>`
    : `<div class="vcard warn"><div class="vsign warn" aria-hidden="true"><span>?</span></div><div class="vtext"><p class="vlabel">Not published</p>` +
      `<p>${esc(r.reason)}</p><p class="vnext"><b>Why:</b> a case is shown only when every number and quote checks out; nothing here is a finding.</p></div></div>`;
  const kinds = {holds: 0, differs: 0, untested: 0};
  for (const c of r.claims || []) kinds[/consistent|matches|holds/i.test(c.verdict) ? "holds" : /differ|contradict/i.test(c.verdict) ? "differs" : "untested"] += 1;
  const tally = (r.claims || []).length ? `<div class="tiles tally">` +
    `<div class="tile"><span class="vsign mini go" aria-hidden="true"><span>✓</span></span><b>${kinds.holds}</b><span>agree with the record</span></div>` +
    `<div class="tile"><span class="vsign mini stop" aria-hidden="true"><span>✕</span></span><b>${kinds.differs}</b><span>differ from the record</span></div>` +
    `<div class="tile"><span class="vsign mini warn" aria-hidden="true"><span>?</span></span><b>${kinds.untested}</b><span>the record cannot test</span></div></div>` : "";
  const claims = (r.claims || []).length ? tally + `<h4>Claims checked against the record</h4><ul>` + r.claims.map(c =>
    `<li>“${esc(c.claim)}”: <b>${esc(c.verdict)}</b>${c.frame ? ` <span class="legend">(${esc(c.frame)})</span>` : ""}</li>`).join("") + `</ul>` : "";
  const finds = (r.findings || []).length ? `<details class="more"><summary>Findings (${r.findings.length})</summary><ul>` + r.findings.map(f =>
    `<li>${esc(f.text)} <span class="legend">[${esc(f.receipt)}]</span></li>`).join("") + `</ul></details>` : "";
  const srcs = (r.sources || []).length ? `<details class="more"><summary>Sources and quotes (${r.sources.length})</summary><ul>` + r.sources.map(s =>
    `<li><a href="${safeUrl(s.url)}" rel="noopener">${esc(s.url)}</a> (${esc(s.quote_check || "unchecked")}): “${esc(s.quote)}”</li>`).join("") + `</ul></details>` : "";
  const fix = r.letter_correction ? `<p class="verdict bad">${esc(r.letter_correction)}</p>` : "";
  const letter = r.letter ? `<details class="more"><summary>Draft letter (review it; nothing is sent)</summary>${fix}<pre class="letter">${esc(r.letter)}</pre></details>` : "";
  const notes = (r.record_notes || []).map(n => `<p class="legend">${esc(n)}</p>`).join("");
  return head + claims + finds + srcs + notes + letter +
    `<p class="legend">Records as of ${esc(r.asof || "")}; $${esc((r.cost_usd || {}).meta)} of Meta API, ${esc(r.turns)} turns, ${Math.round(r.seconds || 0)} s.</p>`;
}

async function liveCases() {
  // real proposals run on the public live site, each verdict as its sign, with the checks made by hand on the city's data
  let d;
  try { d = await getJSON("data/cases.json"); } catch (e) { return ""; }
  if (!(d.cases || []).length) return "";
  return `<section class="cases"><p class="where">Real cases, run live</p><h2 class="corner">New proposals, checked before the money is spent</h2>` +
    d.cases.map(c => `<article class="case"><h3>${esc(c.title)}</h3>` +
      `<p class="legend">${esc(c.run)} · <a href="${safeUrl(c.source.url)}" target="_blank" rel="noopener">${esc(c.source.label)}</a></p>` +
      (c.quote ? `<blockquote>${esc(c.quote)}</blockquote>` : `<p>${esc(c.summary || "")}</p>`) + `<p><b>The question:</b> ${esc(c.question)}</p>` +
      `<ul class="caserows">` + c.results.map(x => `<li><span class="vsign mini ${esc(x.sign)}" aria-hidden="true"><span>${SIGN_GLYPH[x.sign] || "?"}</span></span>` +
        `<span><b>${esc(x.where)}: ${esc(x.label)}</b><br><span class="legend">${esc(x.why)}</span></span></li>`).join("") + `</ul>` +
      `<details class="more"><summary>Checked by hand against the city's own data</summary><ul>${c.proof.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` +
      `<p class="legend">${esc(c.fixed || "")}${c.cost ? ` · ${esc(c.cost)}` : ""}</p></details>` +
      (c.write_up_url ? `<p><a href="${safeUrl(c.write_up_url)}" target="_blank" rel="noopener">The full write-up, with screenshots and the data</a></p>` : "") +
      `</article>`).join("") + `</section>`;
}

async function showDesk() {
  setView("desk");
  // the desk: Muse Spark took a real-world input, searched the live web, worked the case with the checked tools and
  // published only what the gate accepted; refused attempts and every step are in the trace
  history.replaceState(null, "", `#${CITY}/desk`);
  busy("Opening the desk's saved runs…");
  let d;
  try { d = await getJSON("data/desk.json"); } catch (err) { failed(err, "the desk"); return; }
  const badge = s => s === "verified" ? '<span class="status go">quote found in the page</span>' :
    s === "unreadable" ? '<span class="status">page could not be read here: quote unverified</span>' : "";
  // a claim verdict as the current check gives it on the same record: a verdict a later fix changed is shown changed
  const recheck = r => r ? ` <span class="status recheck${/consistent/.test(r.verdict) ? " go" : ""}">current check: ${esc(r.verdict)}` +
    (r.reasons && r.reasons.length ? ` (${esc(r.reasons[0])})` : "") + `</span>` : "";
  const card = c => {
    const f = c.final || {};
    return `<details class="agency"${c.finished ? " open" : ""}><summary><b>${esc(c.kind)} · ${esc(c.city)}</b> ` +
      (c.finished ? `published` : `not published (${esc(c.stopped)})`) + (c.corner ? ` · ${esc(c.corner.split(",")[0])}` : "") +
      ` <span class="legend">${c.turns || 0} steps, ${Math.round(c.seconds || 0)} s, $${Number(c.usd || 0).toFixed(2)}</span></summary>` +
      `<p class="legend">Input: ${esc(c.task)}</p>` +
      (f.summary ? `<p>${esc(f.summary)}</p>` : "") +
      ((f.findings || []).length ? `<ul class="claims">${f.findings.map(x => `<li>${esc(x.text)} <span class="legend">${
        /^https?:/.test(x.receipt || "") ? "from the source page" : esc(x.receipt) + (((c.receipts || {})[x.receipt] || {}).tool ? " · " + esc(c.receipts[x.receipt].tool) : "")
      }</span>${recheck((c.rechecks || {})[x.receipt])}</li>`).join("")}</ul>` : "") +
      ((f.sources || []).length ? `<ul class="claims">${f.sources.map(s => `<li>“${esc(s.quote)}” <a href="${safeUrl(s.url)}" rel="noopener" target="_blank">source</a> ${badge(s.quote_check)}</li>`).join("")}</ul>` : "") +
      (c.letter ? `<details${c.letter_correction ? " open" : ""}><summary>The drafted letter (Muse Spark Open, number-checked)</summary>` +
        (c.letter_correction ? `<p class="verdict bad">${esc(c.letter_correction)}</p>` : "") + `<p class="letter">${esc(c.letter)}</p></details>` : "") +
      `<details><summary>What the agent did, step by step</summary><ol class="legend">` +
      (c.web || []).map(w => `<li>web: ${esc((w.action || {}).type)} ${esc((w.action || {}).query || (w.action || {}).url || "")}</li>`).join("") +
      (c.trace || []).map(t => `<li>${esc(t.tool)}${t.error ? ` — <s>${esc(t.error)}</s> ${esc((t.errors || []).slice(0, 3).join("; "))}` : ""}</li>`).join("") +
      `</ol></details></details>`;
  };
  const pub = d.cases.filter(c => c.finished).length;
  const runs = (d.runs || []).map(r => `<tr><td>${esc(r.id)}</td><td>${r.published} of ${r.cases}</td><td>${r.quotes ? r.verified + " of " + r.quotes : "n/a"}</td><td>$${Number(r.usd_per_case).toFixed(3)}</td><td>${r.seconds_per_case} s</td></tr>`).join("");
  $("out").innerHTML = (await liveCases()) +
    `<p class="where">The desk · saved run ${esc(d.run)} (a replay, not a live endpoint)</p><h2 class="corner">Real cases, worked by agents, checked by code</h2>` +
    `<p class="lede">Each case started from a real input: a news report or official statement found on the live web, or a resident's 311 report with a photo. ` +
    `Muse Spark planned the work, searched, opened the source and investigated the corner with the checked tools; Muse Spark Open drafted the letter. ` +
    `${pub} of ${d.cases.length} passed the publish gate; the rest are shown with the gate's reasons. ` +
    (d.review && d.review.checked ? `Next to each checked claim is the verdict the current claim check gives on the same record: ` +
      `${d.review.changed} of the ${d.review.checked} published verdicts change under the fixes made after this run's review.` : "") + `</p>` +
    (runs ? `<table class="plan"><tr><th>run</th><th>published</th><th>quotes verified on their page</th><th>Meta $ per case</th><th>time per case</th></tr>${runs}</table>` : "") +
    d.cases.map(card).join("");
}

async function showPlan() {
  setView("corners");
  for (const b of $("corners").querySelectorAll("button")) b.setAttribute("aria-current", "false");
  history.replaceState(null, "", `#${CITY}/plan`);
  busy("Opening the city's action plan…");
  let p;
  try { p = await getJSON(`data/${encodeURIComponent(CITY)}/plan.json`); } catch (err) { failed(err, "the plan"); return; }
  const s = p.summary, r = p.regression_to_mean || {}, q = p.requests;
  const n = v => Number(v).toLocaleString("en-US");
  const tiers = Object.entries(s.supported_by_tier || {}).map(([k, v]) => `${v} ${esc(TIER[k] || k)}`).join(", ");
  const repeat = Object.entries(s.repeat_risk_corners || {}).sort((a, b) => b[1] - a[1])[0];
  const tile = (v, label) => `<div class="tile"><b>${v}</b><span>${label}</span></div>`;
  const byName = Object.fromEntries(INDEX.corners.map(c => [c.name, c]));
  const link = name => byName[name] ? `<button class="linkish" data-slug="${esc(byName[name].slug)}">${esc(name)}</button>` : esc(name);
  const rows = [...p.corners].filter(c => c.best).sort((a, b) => b.best.crashes_avoided_per_year - a.best.crashes_avoided_per_year);
  $("out").innerHTML = `<p class="where">${esc(p.city_name)} · records as of ${date(p.asof)}</p>` +
    `<h2 class="corner">Where the evidence says to act first</h2>` +
    `<p class="lede">If each of these ${s.corners} corners got its best low-cost fix, how many injury crashes a year would it avoid?</p>` +
    `<div class="chart">${hbars([
      {label: "The textbook says", value: Math.round(s.textbook_crashes_avoided_per_year), note: "largest estimate at each corner"},
      {label: "The evidence supports", value: Math.round(s.crashes_avoided_per_year_counted_once ?? s.crashes_avoided_per_year_total), sign: "go", note: "without a site visit"},
      ...(r.factor != null && r.factor < 1 ? [{label: "After regression to the mean", value: Math.round(s.crashes_avoided_per_year_counted_once_after_rtm), sign: "go",
        note: "the worst corners partly improve on their own"}] : [])], "injury crashes avoided a year")}` +
    `<p class="legend">The gap rests on studies of other kinds of sites, or on a check nobody has made yet, such as the signal timing.</p></div>` +
    `<div class="tiles">` +
    tile(usd(s.harm_usd_per_year_summed || s.harm_usd_per_year), "a year in harm from these corners' own injury crashes") +
    `<div class="tile" title="${esc(tiers)}"><b>${s.corners_with_supported_fix}</b><span>corners with a supported fix</span></div>` +
    tile(`${s.corners_with_another_road_owner}`, "corners with another road owner") +
    (repeat ? tile(`${repeat[1]}`, `already got ${esc(repeat[0])}; its effect here is unproven`) : "") +
    (q ? tile(`${q.rerequests.length}`, "fixes asked for, turned down, still needed") : "") +
    `</div>` +
    (q && q.rerequests.length ? `<section class="step"><h3>Asked for and turned down</h3>` +
      `<table class="plan"><thead><tr><th>Corner</th><th>Asked for</th><th>Turned down</th><th>Injury crashes since ${esc(date(q.rerequests[0].facts.records_since))}</th><th>Pedestrians hurt</th></tr></thead><tbody>` +
      q.rerequests.map(x => `<tr><td>${link(x.corner)}</td><td>${esc(x.request)} <span class="legend">${esc(x.reference)}</span></td><td>${esc(x.decided)}</td>` +
        `<td class="num">${x.facts.injury_crashes}</td><td class="num">${x.facts.pedestrians_injured}</td></tr>`).join("") +
      `</tbody></table><p class="legend">From ${esc(q.source)}, matched by street names (${q.corners_matched} of ${q.corners} corners). None of these fixes is recorded at the corner now.</p></section>` : "") +
    `<section class="step"><h3>Who must act</h3>` + p.agencies.map(g =>
      `<details class="agency"><summary><b>${esc(g.party)}</b>${g.presumed ? ' <span class="status">presumed</span>' : ""}: ${g.intersections} ${g.intersections === 1 ? "corner" : "corners"}` +
      (g.intersections_with_supported_fix ? `, ${g.crashes_avoided_per_year_total} crashes a year avoidable at ${g.intersections_with_supported_fix}` : "") + `</summary>` +
      (g.letter.body ? `<p class="letter">${esc(g.letter.body)}</p><button class="quiet copy" data-t="${esc(g.letter.body)}">Copy the letter</button>`
                     : `<p class="legend">Letter refused by the number checker: ${esc(g.letter.refused.join("; "))}</p>`) +
      `<table class="plan"><thead><tr><th>Corner</th><th>Injury crashes</th><th>Fix</th><th>Evidence</th></tr></thead><tbody>` +
      g.letter.table.slice(0, 40).map(t => `<tr><td>${link(t.intersection)}</td><td>${t.injury_crashes ?? ""}</td><td>${esc(t.fix || "")}</td>` +
        `<td>${t.fix ? `${esc(t.evidence)}, about ${t.crashes_avoided_per_year} a year` : esc(t.check_first ? "check first: " + t.check_first : t.evidence)}</td></tr>`).join("") +
      `</tbody></table>${g.letter.table.length > 40 ? `<p class="legend">${g.letter.table.length - 40} more in the CSV.</p>` : ""}</details>`).join("") + `</section>` +
    `<section class="step"><h3>Fixes the evidence supports now</h3><table class="plan"><thead><tr><th>Corner</th><th>Fix</th><th>Evidence</th><th>Crashes a year</th><th>Pays for itself under</th></tr></thead><tbody>` +
    rows.slice(0, 30).map(c => `<tr><td>${link(c.name)}</td><td>${esc(c.best.countermeasure)} <span class="legend">CMF ${esc(c.best.cmf_id)}</span></td>` +
      `<td>${esc(TIER[c.best.evidence] || c.best.evidence)}</td><td>${c.best.crashes_avoided_per_year}</td><td>${usd(c.best.pays_for_itself_under_usd)}</td></tr>`).join("") +
    `</tbody></table><p><a href="data/${encodeURIComponent(CITY)}/plan.csv" download>Download the whole plan (CSV)</a></p></section>` +
    `<section class="step"><h3>How to read this</h3><ul class="legend">${p.caveats.map(c => `<li>${esc(c)}</li>`).join("")}` +
    (r.factor != null ? `<li>Regression to the mean: at the worst quarter of ${r.corners} corners with no recorded project, crashes in ${r.years_after.join("–")} were ${pct(r.top_ratio)} of ${r.years_before.join("–")}, against ${pct(r.all_ratio)} at all of them, so ${pct(r.factor)} of a worst corner's count is expected to persist.</li>` : "") +
    `</ul></section>`;
  for (const b of $("out").querySelectorAll("button.linkish")) b.onclick = () => openCorner(INDEX.corners.find(c => c.slug === b.dataset.slug));
  for (const b of $("out").querySelectorAll("button.copy")) b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.t); b.textContent = "Copied"; } catch (e) { b.textContent = "Select the text to copy"; }
  };
}

function listCorners(rows) {
  $("corners").innerHTML = rows.map(c => `<li><button data-slug="${esc(c.slug)}"><span class="rank">${c.rank}</span>` +
    `<span>${c.plan_gap ? `<span class="gapdot" title="no recorded safety work in ${INDEX.years} years"></span>` : ""}${esc(c.name)}</span>` +
    `<span class="n">${c.injury_crashes}</span></button></li>`).join("");
  for (const b of $("corners").querySelectorAll("button"))
    b.onclick = () => openCorner(INDEX.corners.find(c => c.slug === b.dataset.slug));
}

$("search").onsubmit = async e => {
  e.preventDefault();
  const q = $("q").value.trim();
  if (!q || !INDEX) return;
  const words = q.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter(w => (w.length > 2 || /\d/.test(w)) && !["and", "street", "avenue"].includes(w));  // drops "&", state codes
  const hits = INDEX.corners.filter(c => words.every(w => c.name.toLowerCase().includes(w)));
  if (hits.length) { listCorners(hits); if (hits.length === 1) openCorner(hits[0]); return; }
  listCorners(INDEX.corners);
  if (LIVE === null) {
    $("out").innerHTML = `<div class="empty"><h2>That corner is not in this copy.</h2><p>This page holds the reports for ` +
      `the city's ${INDEX.corners.length} ${INDEX.screen === "crash clusters" ? "corners with the most injury crashes" : "priority corners"}. For any other address, run it yourself:</p>` +
      `<p><code>nml engineer "${esc(q)}"</code></p></div>`;
    return;
  }
  busy(`Reading the public record for ${esc(q)}…`);
  try {
    let r = await getJSON(`${LIVE}engineer`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({address: q, city: CITY})});
    while (r.job) {  // a corner never fetched before: the server keeps working and the page asks again
      const job = r.job;
      await new Promise(ok => setTimeout(ok, 3000));
      const rec = await getJSON(`${LIVE}engineer/${encodeURIComponent(job)}`);
      if (rec.status === "failed") throw new Error(rec.error);
      if (rec.status === "running") {
        busy(`Reading the public record for ${esc(q)}… ${Math.round(rec.seconds)} s (a corner nobody asked about before can take a few minutes; public map servers set the pace)`);
        r = {job};
      } else r = rec.result;
    }
    show(r, null);
  }
  catch (err) { failed(err, q); }
};

function wireTags() {
  for (const b of document.querySelectorAll(".rtag")) b.onclick = () => {
    const el = $(`rcpt-${b.dataset.r}`); if (!el) return;
    el.scrollIntoView({behavior: "smooth", block: "center"}); el.classList.add("lit"); setTimeout(() => el.classList.remove("lit"), 1600);
  };
}

function askHTML(a) {
  const tag = id => `<button class="rtag" data-r="${esc(id)}" aria-label="show receipt ${esc(id)}">${esc(id)}</button>`;
  return `<div class="askcard"><p class="q">${esc(a.question)}</p>` +
    (a.answer ? `<p>${esc(a.answer)}</p>` : `<p class="legend">No checked answer (${esc(a.stopped || "stopped")}).</p>`) +
    `<ul class="claims">${(a.claims || []).map(c => `<li>${esc(c.text)}${tag(c.receipt)}</li>`).join("")}</ul>` +
    ((a.refused || []).length ? `<ul class="claims refused">${a.refused.map(x => `<li><s>${esc(x.text)}</s> <span class="legend">refused: ${esc((x.errors || []).join("; "))}</span></li>`).join("")}</ul>` : "") +
    `</div>`;
}

function agentHTML(a) {
  // the case as Muse Spark Open wrote it: it chose the tools and the sentences; the gate refused what the record
  // does not show, and those attempts are kept, struck through, with the reason
  if (!a) return "";
  const tool = id => (a.receipts || {})[id] || id;
  return `<section class="step"><h3>The agent's own case</h3>` +
    `<p class="why">Muse Spark Open chose the tools and wrote these sentences (${a.turns} turns, $${Number(a.usd || 0).toFixed(2)}). ` +
    `The same checker refused ${a.refused.length ? `${a.refused.length} earlier ${a.refused.length === 1 ? "attempt" : "attempts"}, struck through below` : "nothing"}.</p>` +
    (a.summary ? `<p>${esc(a.summary)}</p>` : "") +
    `<ul class="claims">${(a.claims || []).map(c => `<li>${esc(c.text)} <span class="legend">${esc(tool(c.receipt))}</span>` +
      ((c.flags || []).length ? ` <span class="status">flagged by the model-read check</span> <span class="legend">${esc(c.flags.join("; "))}</span>` : "") + `</li>`).join("")}</ul>` +
    ((a.superseded || []).length ? `<p class="legend">Checked again against today's receipts, these no longer pass (the record or a rule changed after the agent wrote them):</p>` +
      `<ul class="claims refused">${a.superseded.map(c => `<li><s>${esc(c.text)}</s> <span class="legend">${esc((c.errors || []).join("; "))}</span></li>`).join("")}</ul>` : "") +
    a.refused.map(x => `<ul class="claims refused">${(x.claims || []).filter(c => x.errors.some(e => e.startsWith(`claim ${x.claims.indexOf(c) + 1}:`)))
      .map(c => `<li><s>${esc(c.text)}</s></li>`).join("")}${x.summary && x.errors.some(e => e.startsWith("summary")) ? `<li><s>${esc(x.summary)}</s></li>` : ""}</ul>` +
      `<p class="legend">Refused: ${esc(x.errors.join("; "))}</p>`).join("") + `</section>`;
}

function busy(text) { $("out").innerHTML = `<p class="busy">${text}</p>`; }
function failed(err, q) {
  $("out").innerHTML = `<div class="empty"><h2>No case for that corner yet.</h2><p>${esc(err.message)}</p>` +
    `<p>Try the two cross streets joined by "&", with the city (and the borough, where there is one), or pick a corner from the list.</p></div>`;
}

async function openCorner(c) {
  setView("corners");
  for (const b of $("corners").querySelectorAll("button")) b.setAttribute("aria-current", b.dataset.slug === c.slug);
  history.replaceState(null, "", `#${CITY}/${c.slug}`);
  busy(`Opening the case for ${esc(c.name)}…`);
  try { show(await getJSON(`data/${encodeURIComponent(CITY)}/j/${encodeURIComponent(c.slug)}.json`), c); } catch (err) { failed(err, c.name); }
}

function show(r, corner) {
  const f = r.findings, fx = f.choose_fixes || {}, cr = fx.crashes || {}, rc = f.root_cause || {}, pg = f.test_programs || {},
    who = f.who_must_act || {owners: [], requesters: []}, lt = f.draft_request || {};
  const j = r.junction;
  if (map) { map.setView([j.lat, j.lon], 15); mapPlaced = true; if (pin) pin.remove(); pin = L.circleMarker([j.lat, j.lon], {radius: 11, color: "#E8A800", weight: 4, fill: false}).addTo(map); }
  // deaths: the larger of the by-mode sum and the dataset's total (some records hold a death with every mode at zero)
  const killed = Math.max((cr.pedestrian_killed || 0) + (cr.cyclist_killed || 0) + (cr.motorist_killed || 0),
                          cr.any_killed || 0, (fx.harm || {}).deaths_in_record || 0);
  const owners = who.owners.length;
  const tag = id => `<button class="rtag" data-r="${esc(id)}" aria-label="show receipt ${esc(id)}">${esc(id)}</button>`;
  const lede = cr.injury_crashes != null ?
    `${cr.injury_crashes} injury ${cr.injury_crashes === 1 ? "crash" : "crashes"} since ${date(cr.since)}${killed ? `, ${killed} ${killed === 1 ? "death" : "deaths"}` : ""}` +
    `${fx.harm ? `, about ${usd(fx.harm.usd_per_year)} a year in harm` : ""}. ` +
    (owners ? `${WORDS[owners] || owners} road ${owners === 1 ? "owner" : "owners"} must act.` : "") : "No crash record is registered for this place.";

  // what the crashes have in common; the corners a share is compared with, as the receipt names them
  const peers = ((rc.baseline || {}).junctions || "the city's priority junctions").replace("screened ", "");
  const mk = f.mechanisms;
  const by = {agent: "AI analyst", grid: "exhaustive search", greedy: "greedy search"};
  const mech = mk && mk.mechanisms && mk.mechanisms.length ? `<div class="mech"><h4>Held up on later years</h4>` +
    `<p class="why">Patterns found in crashes before ${esc(date(mk.split))} and confirmed once on the crashes after it, which the search never saw.</p><ul>` +
    mk.mechanisms.slice(0, 5).map(m => `<li><b>${esc(m.words[0].toUpperCase() + m.words.slice(1))}</b>: ` +
      `${pct(m.explore.share)} before, ${pct(m.sealed.share)} after, against ${pct(m.sealed.city_share)} at ${esc(peers)}` +
      ` <span class="found">${m.found_by.map(x => esc(by[x] || x)).join(" + ")}</span>` +
      (m.mechanism ? `<div class="note">${esc(m.mechanism)}</div>` : "") + `</li>`).join("") + `</ul></div>` : "";
  const pats = (rc.patterns || []).filter(p => p.city_share != null).slice(0, 8);
  const bars = pats.map(p => `<div class="lab ${p.over_represented ? "over" : ""}">${esc(p.phrase || p.pattern)}</div>` +
    `<div class="bar ${p.over_represented ? "over" : ""}" role="img" aria-label="${pct(p.share)} here, ${pct(p.city_share)} at ${esc(peers)}">` +
    `<i style="width:${Math.min(100, 100 * p.share)}%"></i><b class="city" style="left:${Math.min(100, 100 * p.city_share)}%"></b>` +
    `<span>${pct(p.share)} here, ${pct(p.city_share)} at ${esc(peers)}</span></div>`).join("");

  // what the city tried
  const cls = {worked: "s-worked", "not shown": "s-not", "earlier trend": "s-trend", worse: "s-worse"};
  const seen = new Set();
  const progs = (pg.programs || []).filter(p => !seen.has(p.label) && seen.add(p.label)).map(p =>
    `<tr><td><span class="status ${cls[p.status] || "s-not"}">${esc(p.status)}</span></td><td><b>${esc(p.label)}</b><div class="note">${esc(p.text)}</div></td></tr>`).join("");
  const flags = (pg.repeat_risk || []).map(x => `<div class="flag"><b>Tried here before.</b> ${esc(x.text)}</div>`).join("");
  const here = (pg.projects_here || []).filter(p => p.year).map(p => `${esc(p.name)} (${p.year})`).join("; ");

  // the fix and its price
  const fixes = (fx.options || []).slice(0, 6).map(o => `<tr><td><b>${esc(o.countermeasure)}</b>` +
    (o.scale === "reconstruction" ? `<div class="note">reconstruction: needs a design study first</div>` : "") +
    (o.verify_on_site ? `<div class="note">check on site: ${esc(o.verify_on_site)}</div>` : "") +
    (o.local_evidence ? `<div class="note good">Tested on this city's own installs: ${esc(o.local_evidence.text)}</div>` : "") +
    (o.local_program ? `<div class="note">This city tried it (${esc(o.local_program.label)}): ${esc(o.local_program.text)}.</div>` : "") +
    `</td><td class="num">${o.expected_crashes_avoided_per_year}</td><td class="num">${usd(o.harm_avoided_usd_per_year)}</td>` +
    `<td class="legend">CMF ${esc(o.cmf_id)} (${esc(o.cmf)}), ${esc(o.chosen_by)}</td></tr>`).join("");
  const skipped = (fx.not_estimated || []).map(x => `<li><b>${esc(x.countermeasure)}</b>: ${esc(x.reason)}</li>`).join("");
  const sc = f.site_check, word = {present: "seen", absent: "not seen", unsure: "unsure"};
  const site = sc ? `<div class="mech"><h4>What the aerial photo shows</h4><p class="why">Muse Spark reads the state aerial photo; ` +
    `SAM 3.1 must find each thing it points at. A feature changes a recommendation only if, scored against the city's own map layers, it met its accuracy rule and beat always giving the most common answer.` +
    (Object.values(sc.answers).some(v => v.reliable) ? "" : " None has yet.") + `</p><ul>` +
    Object.entries(sc.answers).map(([a, v]) => `<li><b>${esc(a.replace(/_/g, " "))}</b>: ${esc(word[v.answer] || v.answer)}` +
      (v.reliable ? "" : ` <span class="legend">(not reliable enough to act on)</span>`) +
      (v.reliable && v.answer === "present" && v.fix_if_present ? ` <span class="found">${esc(v.fix_if_present)} already there</span>` : "") +
      `</li>`).join("") + `</ul></div>` : "";

  // who must act
  const ownerCards = who.owners.map(o => `<div class="owner ${o.confidence === "recorded" ? "" : "inferred"}"><b>${esc(o.party)}</b>` +
    `<p class="roads">${esc(o.roads.join(", "))}</p><p class="basis">${o.confidence === "recorded" ? "Owner recorded in" : o.confidence === "inferred" ? "Not listed in" : "Route tag only, from"} ${esc((o.basis || {}).dataset || "the record")}` +
    `${o.inferred_roads && o.inferred_roads.length ? `; ${esc(o.inferred_roads.join(", "))} not listed there, so inferred` : ""}</p></div>`).join("");
  const reqs = who.requesters.length ? `<p class="req">Who can push for it: ${who.requesters.map(x => `<b>${esc(x.party)}</b>`).join(" and ")}.</p>` : "";

  // the request
  const facts = lt.facts || {};
  const letter = lt.letter ? `<textarea id="letter" aria-label="Request letter">${esc(lt.letter)}</textarea>` +
      `<p class="legend">Every number was checked against the record before the letter was shown. Review it and send it yourself; NearMissLens sends nothing. <button class="quiet" id="copy" type="button">Copy the letter</button></p>`
    : `<p class="why">To ${esc(facts.to || "the road owners")}${facts.copy_to ? `, copying ${esc(facts.copy_to)}` : ""}. The facts are ready; the letter is drafted by Muse Spark Open and checked number by number.</p>` +
      (LIVE !== null ? `<button id="draft" type="button">Draft the letter</button><div id="draftout"></div>` : `<p class="legend">Run <code>nml engineer --letter "${esc(j.name)}"</code> to draft it.</p>`);

  const receipts = r.receipts.map(x => `<div class="receipt" id="rcpt-${esc(x.id)}"><h4>${esc(x.id)} ${esc(x.tool.replace(/_/g, " "))} <span class="legend">${x.seconds} s</span></h4>` +
    `<div class="legend">${esc(x.summary)}</div><ul>${x.sources.map(s => `<li>source: ${esc(s)}</li>`).join("")}${x.checks.map(c => `<li>check: ${esc(c)}</li>`).join("")}</ul></div>`).join("");

  const media = r.media && r.media.aerial ? `<img class="aerial" src="${esc(r.media.aerial)}" alt="City aerial photo of the corner">` : "";
  $("out").innerHTML = `
    <p class="where">${corner ? `Corner ${corner.rank} of ${INDEX.corners.length} by injury crashes` : "Searched corner"}</p>
    <h2 class="corner">${esc(j.name.split(",")[0])}</h2>
    <p class="lede">${esc(lede)}</p>
    <p class="meta">Built in ${r.seconds < 1 ? "under a second" : `${Math.round(r.seconds)} s`} from records as of ${date(r.asof)}. ${r.claim_errors.length ? `${r.claim_errors.length} claims refused by the checker.` : "Every claim passed the number checker."}</p>
    ${cornerGlance(cr, fx, killed, owners)}
    ${media}
    <section class="step"><h3><span class="no">1</span>The case</h3>
      <p class="why">Each sentence names the receipt behind it. A sentence whose numbers do not match its receipt is refused before it is shown.</p>
      <ul class="claims">${r.claims.map(c => `<li>${esc(c.text)}${tag(c.receipt)}</li>`).join("")}</ul></section>
    <section class="step"><h3><span class="no">2</span>What the crashes have in common</h3>
      <p class="why">${rc.crashes ?? "?"} police-reported crashes at this corner. Yellow marks a pattern that is more common here than at ${esc(peers)} after a correction for testing many patterns; the line marks the city's share. Police factors are an officer's account, not a proven cause.</p>
      <div class="bars">${bars || '<p class="legend">Too few crashes to compare.</p>'}</div>
      ${rc.not_recorded && rc.not_recorded.length ? `<p class="legend">Not recorded in this dataset: ${esc(rc.not_recorded.join(", "))}.</p>` : ""}
      ${rc.factor_unspecified_share != null ? `<p class="legend">${pct(rc.factor_unspecified_share)} of these crashes have no contributing factor recorded.</p>` : ""}
      ${mech}</section>
    <section class="step"><h3><span class="no">3</span>What the city already tried</h3>
      <p class="why">Each program was tested on the city's own crash records against places treated later, with a fake install date that must show nothing.</p>
      ${flags}<table><tbody>${progs || '<tr><td class="legend">No program in this city has been tested yet.</td></tr>'}</tbody></table>
      <p class="legend">Recorded safety work at this corner: ${here || "none in the city's project records"}.</p></section>
    <section class="step"><h3><span class="no">4</span>The fix and its price</h3>
      <p class="why">Federal Proven Safety Countermeasures, estimated only where a crash-reduction study matches this corner's control (${esc(fx.control || "unknown")}) and the crashes it targets. Dollars use the U.S. DOT's crash costs.</p>
      ${(fx.options || []).length ? hbars(fx.options.slice(0, 6).map(o => ({label: esc(o.countermeasure), value: o.injury_crashes_avoided_per_year,
          track: o.target_crashes_per_year, sign: o.verify_on_site ? "warn" : "go",
          note: o.verify_on_site ? "check on site first" : esc(o.evidence || o.chosen_by || "")})), "injury crashes avoided a year") : ""}
      <details class="more"><summary>Every fix, its harm avoided and its study</summary>
      <table class="fixes"><thead><tr><th>Fix</th><th>Crashes avoided a year</th><th>Harm avoided a year</th><th>Study</th></tr></thead><tbody>${fixes}</tbody></table></details>
      ${skipped ? `<details><summary>${(fx.not_estimated || []).length} more fixes without a number, and why</summary><ul class="legend">${skipped}</ul></details>` : ""}
      ${site}</section>
    <section class="step"><h3><span class="no">5</span>Who must act</h3>
      <p class="why">Road owners from the road inventory; streets it does not list are marked as inferred. Offices from the city's district maps.</p>
      <div class="owners">${ownerCards || '<p class="legend">No road owner found in the registered datasets.</p>'}</div>${reqs}</section>
    <section class="step"><h3><span class="no">6</span>The request</h3>${letter}</section>
    ${agentHTML(r.agent)}
    ${LIVE !== null ? `<section class="step"><h3>Published about this corner</h3>
      <p class="why">Muse Spark searches the web for agency pages, council items and news about this corner; code opens each page and keeps it only if the passage is on it and the page names both streets.</p>
      <button id="findreports" type="button" class="quiet">Search the web</button><div id="reportsout"></div></section>` : ""}
    <section class="step"><h3>Ask the engineer</h3>
      <p class="why">Muse Spark Open answers from this corner's receipts. Every sentence names its receipt; sentences the checker refuses are shown struck through with the reason.</p>
      ${LIVE !== null && corner ? `<form id="askform" class="search ask"><input id="askq" maxlength="300" placeholder="e.g. Why are trucks over-represented here, and who can fix it?"><button>Ask</button></form><div id="askout"></div>` : ""}
      ${LIVE !== null && !corner ? `<p class="legend">Questions are answered for the city's listed corners, whose receipts are saved; this searched corner's case above is complete.</p>` : ""}
      ${(r.asks || []).map(askHTML).join("") || (LIVE === null ? '<p class="legend">Questions are answered on the live page.</p>' : "")}</section>
    <section class="step"><h3>Receipts</h3><div class="receipts">${receipts}</div></section>`;

  if ($("copy")) $("copy").onclick = () => navigator.clipboard.writeText($("letter").value);
  if ($("askform")) $("askform").onsubmit = async e => {
    e.preventDefault();
    const q = $("askq").value.trim(); if (!q) return;
    $("askout").innerHTML = `<p class="legend">Reading the receipts…</p>`;
    try {
      const res = await getJSON(`${LIVE}ask`, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({city: CITY, slug: corner ? corner.slug : "", question: q})});
      $("askout").innerHTML = askHTML(res); wireTags();
    } catch (err) { $("askout").innerHTML = `<p>${esc(err.message)}</p>`; }
  };
  wireTags();
  if ($("findreports")) $("findreports").onclick = () => {
    $("findreports").disabled = true;
    findJob({city: CITY, corner: j.name.split(",")[0]}, $("reportsout"), res => { $("reportsout").innerHTML = foundPages(res); });
  };
  if ($("draft")) $("draft").onclick = async () => {
    $("draft").disabled = true; $("draftout").innerHTML = `<p class="legend">Drafting and checking…</p>`;
    try {
      const res = await getJSON(`${LIVE}letter`, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: j.name, lat: j.lat, lon: j.lon, city: CITY})});
      $("draftout").innerHTML = res.letter ? `<textarea aria-label="Request letter">${esc(res.letter)}</textarea>` +
        `<p class="legend">${res.rejected_drafts ? `${res.rejected_drafts} draft(s) refused by the checker and fixed. ` : ""}Review it and send it yourself.</p>`
        : `<p>The checker refused every draft: ${esc((res.checker_errors || []).join("; "))}</p>`;
    } catch (err) { $("draftout").innerHTML = `<p>${esc(err.message)}</p>`; $("draft").disabled = false; }
  };
  pathNav();
  $("out").focus?.();
  window.scrollTo({top: 0});
}

function pathNav() {
  // the corner's report as a path of its sections, each a jump, so the page reads like a flow chart
  const secs = [...$("out").querySelectorAll("section.step")].filter(x => x.querySelector("h3 .no"));  // the numbered steps only
  const meta = $("out").querySelector("p.meta");
  if (secs.length < 3 || !meta) return;
  const nav = document.createElement("nav");
  nav.className = "jump";
  nav.setAttribute("aria-label", "This report, step by step");
  nav.innerHTML = secs.map((x, i) => `<a href="#" data-i="${i}">${esc(x.querySelector("h3").textContent.replace(/^\s*\d+\s*/, ""))}</a>`).join("");
  nav.onclick = e => {
    const a = e.target.closest("a[data-i]");
    if (!a) return;
    e.preventDefault();
    secs[+a.dataset.i].scrollIntoView({behavior: "smooth", block: "start"});
  };
  meta.after(nav);
}

boot();
