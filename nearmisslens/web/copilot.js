// NearMissLens copilot. One page for the static site (precomputed reports in data/) and the live server (the same
// data/ paths, plus POST engineer and letter for corners that are not precomputed).
"use strict";
const meta = n => (document.querySelector(`meta[name="${n}"]`) || {}).content || "";
const MODE = meta("nml-mode") === "live" ? "live" : "static";
const LIVE = MODE === "live" ? "" : (meta("nml-live").startsWith("https://") ? meta("nml-live").replace(/\/?$/, "/") : null);
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const usd = v => v == null ? "n/a" : v >= 1e6 ? `$${(v / 1e6).toFixed(1)} million` : `$${Math.round(v).toLocaleString("en-US")}`;
const pct = v => `${Math.round(100 * v)}%`;
const date = s => s ? new Date(s + "T12:00:00").toLocaleDateString("en-GB", {day: "numeric", month: "long", year: "numeric"}) : "";
let INDEX = null, map = null, layer = null, pin = null;

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  let body = null;
  try { body = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok || !body) throw new Error((body && body.error) || `the server answered ${r.status}`);
  if (body.error) throw new Error(body.error);
  return body;
}

async function boot() {
  try { INDEX = await getJSON("data/index.json"); } catch (e) {
    $("citynote").textContent = `The corner list did not load (${e.message}).`; return;
  }
  const s = INDEX.summary || {};
  $("citynote").innerHTML = `<b>${INDEX.corners.length}</b> ${esc(INDEX.city_name)} priority corners, worst first. ` +
    `<span class="gapdot"></span><b>${s.plan_gap ?? "?"}</b> had at least 10 injury crashes and no recorded safety work in five years. ` +
    `Together their ${Number(s.injury_crashes_distinct || 0).toLocaleString("en-US")} injury crashes cost about ` +
    `${usd(s.harm_usd_per_year)} a year. Records as of ${date(INDEX.asof)}.`;
  const [sLat, wLon, nLat, eLon] = INDEX.bbox;
  map = L.map("map", {scrollWheelZoom: false}).fitBounds([[sLat, wLon], [nLat, eLon]]);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, attribution: "© OpenStreetMap contributors"}).addTo(map);
  layer = L.layerGroup().addTo(map);
  const css = getComputedStyle(document.documentElement);
  const red = css.getPropertyValue("--stop").trim(), grey = css.getPropertyValue("--mut").trim();
  for (const c of INDEX.corners) {
    L.circleMarker([c.lat, c.lon], {radius: 3 + Math.sqrt(c.injury_crashes || 0) / 2, color: c.plan_gap ? red : grey,
      weight: 1, fillOpacity: .55}).bindTooltip(`${esc(c.name)}: ${c.injury_crashes} injury crashes`)
      .on("click", () => openCorner(c)).addTo(layer);
  }
  listCorners(INDEX.corners);
  const want = new URLSearchParams(location.search).get("c") || location.hash.slice(1);
  const hit = want && INDEX.corners.find(c => c.slug === want);
  if (hit) openCorner(hit);
}

function listCorners(rows) {
  $("corners").innerHTML = rows.map(c => `<li><button data-slug="${esc(c.slug)}"><span class="rank">${c.rank}</span>` +
    `<span>${c.plan_gap ? '<span class="gapdot" title="no recorded safety work in five years"></span>' : ""}${esc(c.name)}</span>` +
    `<span class="n">${c.injury_crashes}</span></button></li>`).join("");
  for (const b of $("corners").querySelectorAll("button"))
    b.onclick = () => openCorner(INDEX.corners.find(c => c.slug === b.dataset.slug));
}

$("search").onsubmit = async e => {
  e.preventDefault();
  const q = $("q").value.trim();
  if (!q || !INDEX) return;
  const words = q.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter(w => w.length > 1 && !["and", "ny", "street", "avenue"].includes(w));
  const hits = INDEX.corners.filter(c => words.every(w => c.name.toLowerCase().includes(w)));
  if (hits.length) { listCorners(hits); if (hits.length === 1) openCorner(hits[0]); return; }
  listCorners(INDEX.corners);
  if (LIVE === null) {
    $("out").innerHTML = `<div class="empty"><h2>That corner is not in this copy.</h2><p>This page holds the reports for ` +
      `the city's ${INDEX.corners.length} priority corners. For any other address, run it yourself:</p>` +
      `<p><code>nml engineer "${esc(q)}"</code></p></div>`;
    return;
  }
  busy(`Reading the public record for ${esc(q)}…`);
  try { show(await getJSON(`${LIVE}engineer`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({address: q})}), null); }
  catch (err) { failed(err, q); }
};

function busy(text) { $("out").innerHTML = `<p class="busy">${text}</p>`; }
function failed(err, q) {
  $("out").innerHTML = `<div class="empty"><h2>No case for that corner yet.</h2><p>${esc(err.message)}</p>` +
    `<p>Try the cross streets with the borough, e.g. "Delancey Street & Essex Street, Manhattan, NY", or pick a corner from the list.</p></div>`;
}

async function openCorner(c) {
  for (const b of $("corners").querySelectorAll("button")) b.setAttribute("aria-current", b.dataset.slug === c.slug);
  history.replaceState(null, "", `#${c.slug}`);
  busy(`Opening the case for ${esc(c.name)}…`);
  try { show(await getJSON(`data/j/${encodeURIComponent(c.slug)}.json`), c); } catch (err) { failed(err, c.name); }
}

function show(r, corner) {
  const f = r.findings, fx = f.choose_fixes || {}, cr = fx.crashes || {}, rc = f.root_cause || {}, pg = f.test_programs || {},
    who = f.who_must_act || {owners: [], requesters: []}, lt = f.draft_request || {};
  const j = r.junction;
  if (map) { map.setView([j.lat, j.lon], 15); if (pin) pin.remove(); pin = L.circleMarker([j.lat, j.lon], {radius: 11, color: "#E8A800", weight: 4, fill: false}).addTo(map); }
  const killed = (cr.pedestrian_killed || 0) + (cr.cyclist_killed || 0) + (cr.motorist_killed || 0);
  const owners = who.owners.length;
  const tag = id => `<button class="rtag" data-r="${esc(id)}" aria-label="show receipt ${esc(id)}">${esc(id)}</button>`;
  const lede = cr.injury_crashes != null ?
    `${cr.injury_crashes} injury crashes since ${date(cr.since)}${killed ? `, ${killed} ${killed === 1 ? "death" : "deaths"}` : ""}` +
    `${fx.harm ? `, about ${usd(fx.harm.usd_per_year)} a year in harm` : ""}. ` +
    (owners ? `${owners === 1 ? "One road owner" : `${owners} road owners`} must act.` : "") : "No crash record is registered for this place.";

  // what the crashes have in common
  const pats = (rc.patterns || []).filter(p => p.city_share != null).slice(0, 8);
  const bars = pats.map(p => `<div class="lab ${p.over_represented ? "over" : ""}">${esc(p.phrase || p.pattern)}</div>` +
    `<div class="bar ${p.over_represented ? "over" : ""}" role="img" aria-label="${pct(p.share)} here, ${pct(p.city_share)} at the city's priority corners">` +
    `<i style="width:${Math.min(100, 100 * p.share)}%"></i><b class="city" style="left:${Math.min(100, 100 * p.city_share)}%"></b>` +
    `<span>${pct(p.share)} here, ${pct(p.city_share)} citywide</span></div>`).join("");

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

  // who must act
  const ownerCards = who.owners.map(o => `<div class="owner ${o.confidence === "recorded" ? "" : "inferred"}"><b>${esc(o.party)}</b>` +
    `<p class="roads">${esc(o.roads.join(", "))}</p><p class="basis">${o.confidence === "recorded" ? "Owner recorded in" : o.confidence === "inferred" ? "Not listed in" : "Route tag only, from"} ${esc((o.basis || {}).dataset || "the record")}</p></div>`).join("");
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
    <p class="meta">Built in ${r.seconds} s from records as of ${date(r.asof)}. ${r.claim_errors.length ? `${r.claim_errors.length} claims refused by the checker.` : "Every claim passed the checker."}</p>
    ${media}
    <section class="step"><h3><span class="no">1</span>The case</h3>
      <p class="why">Each sentence names the receipt behind it. A sentence whose numbers do not match its receipt is refused before it is shown.</p>
      <ul class="claims">${r.claims.map(c => `<li>${esc(c.text)}${tag(c.receipt)}</li>`).join("")}</ul></section>
    <section class="step"><h3><span class="no">2</span>What the crashes have in common</h3>
      <p class="why">${rc.crashes ?? "?"} police-reported crashes within ${rc.radius_m ?? 100} m. Yellow marks a pattern that is more common here than at the city's priority corners after a correction for testing many patterns; the line marks the city's share. Police factors are an officer's account, not a proven cause.</p>
      <div class="bars">${bars || '<p class="legend">Too few crashes to compare.</p>'}</div>
      ${rc.not_recorded && rc.not_recorded.length ? `<p class="legend">Not recorded in this dataset: ${esc(rc.not_recorded.join(", "))}.</p>` : ""}
      ${rc.factor_unspecified_share != null ? `<p class="legend">${pct(rc.factor_unspecified_share)} of these crashes have no contributing factor recorded.</p>` : ""}</section>
    <section class="step"><h3><span class="no">3</span>What the city already tried</h3>
      <p class="why">Each program was tested on the city's own crash records against places treated later, with a fake install date that must show nothing.</p>
      ${flags}<table><tbody>${progs || '<tr><td class="legend">No program in this city has been tested yet.</td></tr>'}</tbody></table>
      <p class="legend">Recorded safety work at this corner: ${here || "none in the city's project records"}.</p></section>
    <section class="step"><h3><span class="no">4</span>The fix and its price</h3>
      <p class="why">Federal Proven Safety Countermeasures, estimated only where a crash-reduction study matches this corner's control (${esc(fx.control || "unknown")}) and the crashes it targets. Dollars use the U.S. DOT's crash costs.</p>
      <table class="fixes"><thead><tr><th>Fix</th><th>Crashes avoided a year</th><th>Harm avoided a year</th><th>Study</th></tr></thead><tbody>${fixes}</tbody></table>
      ${skipped ? `<details><summary>${(fx.not_estimated || []).length} more fixes without a number, and why</summary><ul class="legend">${skipped}</ul></details>` : ""}</section>
    <section class="step"><h3><span class="no">5</span>Who must act</h3>
      <p class="why">Road owners from the road inventory; streets it does not list are marked as inferred. Offices from the city's district maps.</p>
      <div class="owners">${ownerCards || '<p class="legend">No road owner found in the registered datasets.</p>'}</div>${reqs}</section>
    <section class="step"><h3><span class="no">6</span>The request</h3>${letter}</section>
    <section class="step"><h3>Receipts</h3><div class="receipts">${receipts}</div></section>`;
  for (const b of document.querySelectorAll(".rtag")) b.onclick = () => {
    const el = $(`rcpt-${b.dataset.r}`); if (!el) return;
    el.scrollIntoView({behavior: "smooth", block: "center"}); el.classList.add("lit"); setTimeout(() => el.classList.remove("lit"), 1600);
  };
  if ($("copy")) $("copy").onclick = () => navigator.clipboard.writeText($("letter").value);
  if ($("draft")) $("draft").onclick = async () => {
    $("draft").disabled = true; $("draftout").innerHTML = `<p class="legend">Drafting and checking…</p>`;
    try {
      const res = await getJSON(`${LIVE}letter`, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: j.name, lat: j.lat, lon: j.lon})});
      $("draftout").innerHTML = res.letter ? `<textarea aria-label="Request letter">${esc(res.letter)}</textarea>` +
        `<p class="legend">${res.rejected_drafts ? `${res.rejected_drafts} draft(s) refused by the checker and fixed. ` : ""}Review it and send it yourself.</p>`
        : `<p>The checker refused every draft: ${esc((res.checker_errors || []).join("; "))}</p>`;
    } catch (err) { $("draftout").innerHTML = `<p>${esc(err.message)}</p>`; $("draft").disabled = false; }
  };
  $("out").focus?.();
  window.scrollTo({top: 0});
}

boot();
