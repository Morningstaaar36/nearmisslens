import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const md = (s) => DOMPurify.sanitize(marked.parse(String(s ?? "").replace(/</g, "&lt;")),
  { FORBID_TAGS: ["img", "style", "iframe", "form"], FORBID_ATTR: ["style"] });
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const NAME = { vehicle: "car", two_wheeler: "two-wheeler", pedestrian: "pedestrian" };
const HEIGHT_M = { vehicle: 1.5, two_wheeler: 1.3, pedestrian: 1.7 };
const COLOUR = { vehicle: "#d9dee2", two_wheeler: "#7fb3d5", pedestrian: "#c39bd3" };
const SIGNAL = { G: "green", y: "yellow", r: "red" };
const WINDOW = [-4, 3];

const st = { index: null, view: null, img: null, rank: 1, mode: "2d", replay: 0, t: WINDOW[0], playing: false, fit: null };
const hash = new URLSearchParams(location.hash.slice(1));

const finding = () => st.view.facts.findings.find((f) => f.rank === st.rank);
const users = (pair) => pair.map((p) => NAME[p] || p).join(" and ");
const fmt = (v, d = 1) => (v === null || v === undefined ? "n/a" : Number(v).toFixed(d));

async function init() {
  st.index = await (await fetch("data/index.json")).json();
  const sel = $("audit");
  for (const a of st.index.audits) sel.add(new Option(a.title, a.key));
  if (!st.index.audits.length) {
    $("rail").innerHTML = '<p class="empty">No audit exported yet. Run <code>nml export dev</code>.</p>';
    return;
  }
  sel.value = st.index.audits.some((a) => a.key === hash.get("audit")) ? hash.get("audit") : st.index.audits[0].key;
  sel.onchange = () => load(sel.value);
  $("v2d").onclick = () => setMode("2d");
  $("v3d").onclick = () => setMode("3d");
  $("play").onclick = () => { st.playing = !st.playing; $("play").textContent = st.playing ? "Pause" : "Play"; };
  $("time").oninput = (e) => { st.playing = false; $("play").textContent = "Play"; setTime(+e.target.value); };
  $("event").onchange = (e) => { st.replay = +e.target.value; buildReplay(); };
  $("map").onclick = pickHotspot;
  addEventListener("resize", () => { drawMap(); sizeThree(); });
  renderScore();
  await load(sel.value);
  if (hash.get("hotspot")) selectHotspot(+hash.get("hotspot"));
  if (hash.get("view") === "3d") setMode("3d");
  if (hash.get("t")) setTime(+hash.get("t"));
}

async function load(key) {
  st.view = await (await fetch(`data/${key}.json`)).json();
  st.img = await new Promise((ok, fail) => {
    const im = new Image();
    im.onload = () => ok(im);
    im.onerror = fail;
    im.src = `data/media/${st.view.map.image}`;
  });
  st.fit = bounds();
  st.rank = st.view.facts.findings[0]?.rank ?? 1;
  st.replay = 0;
  $("source").textContent = `${st.view.site} ${st.view.clip}, ${(st.view.facts.observed_s / 60).toFixed(1)} min. Tracks: ${st.view.source}.`;
  $("legend").innerHTML = `<i style="background:${css("--conflict")}"></i>PET conflict (≤ ${st.view.facts.thresholds.pet_s} s)` +
    `<i style="background:${css("--amber")}"></i>TTC conflict (≤ ${st.view.facts.thresholds.ttc_s} s)` +
    `<i class="sq"></i>Hotspot, ${st.view.facts.thresholds.cell_m} m cell`;
  renderRail();
  renderPanel();
  renderSignals();
  renderVoice();
  $("memo").innerHTML = md(st.view.memo);
  if (three) disposeTextures();
  drawMap();
  if (st.mode === "3d") buildReplay();
  saveHash();
}

function saveHash() {
  const h = new URLSearchParams({ audit: st.view.key, hotspot: st.rank, view: st.mode });
  history.replaceState(null, "", `#${h}`);
}

/* ---------- 2D map ---------- */

function bounds() {
  const c = st.view.conflicts;
  const xs = [...(c.x || []), ...st.view.facts.findings.map((f) => f.x)];
  const ys = [...(c.y || []), ...st.view.facts.findings.map((f) => f.y)];
  const m = st.view.map;
  if (!xs.length) {
    return { x0: m.x0, x1: m.x0 + m.width * m.mpp_x, y0: m.y0 - m.height * m.mpp_y, y1: m.y0 };
  }
  const pad = 15;
  return { x0: Math.min(...xs) - pad, x1: Math.max(...xs) + pad, y0: Math.min(...ys) - pad, y1: Math.max(...ys) + pad };
}

function projector(canvas) {
  const b = st.fit;
  const s = Math.min(canvas.width / (b.x1 - b.x0), canvas.height / (b.y1 - b.y0));
  const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2;
  return { s, px: (x) => (x - cx) * s + canvas.width / 2, py: (y) => (cy - y) * s + canvas.height / 2,
           wx: (px) => (px - canvas.width / 2) / s + cx, wy: (py) => cy - (py - canvas.height / 2) / s };
}

function drawMap() {
  if (!st.view) return;
  const cv = $("map");
  const dpr = devicePixelRatio || 1;
  cv.width = cv.clientWidth * dpr;
  cv.height = cv.clientHeight * dpr;
  const g = cv.getContext("2d");
  const P = projector(cv);
  const m = st.view.map;
  g.fillStyle = css("--asphalt");
  g.fillRect(0, 0, cv.width, cv.height);
  g.drawImage(st.img, P.px(m.x0), P.py(m.y0), m.width * m.mpp_x * P.s, m.height * m.mpp_y * P.s);
  g.fillStyle = "rgba(20,26,30,0.35)";
  g.fillRect(0, 0, cv.width, cv.height);
  const c = st.view.conflicts;
  for (let i = 0; i < (c.x || []).length; i++) {
    g.beginPath();
    g.arc(P.px(c.x[i]), P.py(c.y[i]), 3.2 * dpr, 0, 2 * Math.PI);
    g.fillStyle = c.measure[i] === "PET" ? css("--conflict") : css("--amber");
    g.globalAlpha = 0.9;
    g.fill();
  }
  g.globalAlpha = 1;
  for (const f of st.view.facts.findings) {
    const half = f.cell_m / 2;
    const x = P.px(f.x - half), y = P.py(f.y + half), w = f.cell_m * P.s;
    const on = f.rank === st.rank;
    if (on) { g.fillStyle = "rgba(232,184,30,0.18)"; g.fillRect(x, y, w, w); }
    g.lineWidth = (on ? 4 : 2.5) * dpr;
    g.strokeStyle = css("--marking");
    g.strokeRect(x, y, w, w);
    g.font = `800 ${14 * dpr}px Overpass, sans-serif`;
    const label = String(f.rank), pad = 5 * dpr, tw = g.measureText(label).width + 2 * pad;
    g.fillStyle = css("--marking");
    g.fillRect(x, y - 20 * dpr, tw, 20 * dpr);
    g.fillStyle = "#1d2a33";
    g.fillText(label, x + pad, y - 5 * dpr);
  }
}

function pickHotspot(e) {
  const cv = $("map"), dpr = devicePixelRatio || 1, r = cv.getBoundingClientRect();
  const P = projector(cv);
  const x = P.wx((e.clientX - r.left) * dpr), y = P.wy((e.clientY - r.top) * dpr);
  const hit = st.view.facts.findings.find((f) => Math.abs(x - f.x) <= f.cell_m / 2 && Math.abs(y - f.y) <= f.cell_m / 2);
  if (hit) selectHotspot(hit.rank);
}

function selectHotspot(rank) {
  if (!st.view.facts.findings.some((f) => f.rank === rank)) return;
  st.rank = rank;
  st.replay = 0;
  renderRail();
  drawMap();
  if (st.mode === "3d") buildReplay();
  saveHash();
}

/* ---------- hotspot rail ---------- */

function renderRail() {
  const fs = st.view.facts.findings;
  const f = finding();
  if (!f) {
    $("rail").innerHTML = '<h2>No hotspots</h2><p class="empty">No cell reached the hotspot threshold in this audit.</p>';
    return;
  }
  const d = f.dominant;
  const sev = [d.min_pet_s != null ? `closest PET ${d.min_pet_s} s` : "", d.min_ttc_s != null ? `lowest TTC ${d.min_ttc_s} s` : ""].filter(Boolean).join(", ");
  const moves = Object.entries(d.movements || {}).map(([k, v]) => `${v} ${k.replace("_", "-")}`).join(", ");
  const entry = Object.entries(d.entry_signal || {}).map(([k, v]) => `${v} ${SIGNAL[k] || k}`).join(", ");
  let h = `<div class="picker" role="group" aria-label="Hotspots">${fs.map((x) =>
    `<button data-r="${x.rank}" aria-pressed="${x.rank === f.rank}">${x.rank}</button>`).join("")}</div>`;
  h += `<h2>Hotspot ${f.rank}</h2>`;
  h += `<p class="rate">${fmt(f.rate_per_1000)} <small>conflicts per 1,000 road users</small></p>`;
  h += `<p class="why">95% CI ${fmt(f.ci95[0])} to ${fmt(f.ci95[1])}. ${f.events} conflicts among ${f.users} road users through a ${f.cell_m} m cell.</p>`;
  h += `<p>Most are ${esc(d.type.replace("_", "-"))} conflicts between ${esc(users(d.pair))} (${d.events}${sev ? `; ${sev}` : ""}).</p>`;
  if (moves) h += `<p class="why">Their movements: ${esc(moves)}.${entry ? ` Signal when they entered: ${esc(entry)}.` : ""}</p>`;
  if (f.verification) {
    const v = f.verification;
    h += `<p class="verdict">Muse Spark watched the ${v.reviewed} most severe on video: ${v.real} real, ${v.reviewed - v.real} not, ${v.evasive} with braking or swerving.</p>`;
  }
  if (f.replays?.length) h += `<p><button id="to3d" class="seg-like">Replay the closest conflict in 3D</button></p>`;
  h += "<h3>Countermeasures that fit</h3>";
  if (f.countermeasures.length) {
    h += `<table><thead><tr><th>FHWA countermeasure</th><th class="num">CMF</th><th class="num">Fewer crashes</th><th>Rating</th></tr></thead><tbody>${
      f.countermeasures.map((m) => `<tr><td>${esc(m.psc)}<br><span class="why">CMF Clearinghouse ID ${esc(m.crfid)}, ${esc(m.crash_type)}</span></td>` +
        `<td class="num">${fmt(m.cmf, 2)}</td><td class="num">${fmt(m.crf_pct, 0)}%</td><td>${esc(m.stars)}</td></tr>`).join("")}</tbody></table>`;
    const notes = [...new Set(f.countermeasures.map((m) => m.note).filter(Boolean))];
    if (notes.length) h += `<p class="why">${notes.map(esc).join(" ")}</p>`;
  } else {
    h += '<p class="empty">No FHWA Proven Safety Countermeasure has a crash-reducing CMF for this conflict here.</p>';
  }
  if (f.rejected.length) {
    h += `<details><summary>Considered and rejected (${f.rejected.length})</summary><ul>${
      f.rejected.map((r) => `<li>${esc(r.psc)}${r.crfid ? ` (CMF ${esc(r.crfid)})` : ""}: ${esc(r.reason)}</li>`).join("")}</ul></details>`;
  }
  if (f.illustration?.image) {
    const il = f.illustration;
    h += `<figure class="fig"><img src="data/${esc(il.image)}" alt="Observed frame and an AI-generated illustration of ${esc(il.countermeasure)} at this hotspot">` +
      `<figcaption>Left: drone frame. Right: Muse Image illustration of ${esc(il.countermeasure)}, AI-generated, not a design. ` +
      `SAM 3.1 ${il.check_passed ? "found" : "did not find"} '${esc(il.check_concept)}' in the hotspot after the edit.</figcaption></figure>`;
  }
  $("rail").innerHTML = h;
  $("rail").querySelectorAll(".picker button").forEach((b) => (b.onclick = () => selectHotspot(+b.dataset.r)));
  if ($("to3d")) $("to3d").onclick = () => setMode("3d");
}

/* ---------- 3D replay ---------- */

let three = null;

function setMode(mode) {
  st.mode = mode;
  $("v2d").setAttribute("aria-selected", mode === "2d");
  $("v3d").setAttribute("aria-selected", mode === "3d");
  $("map").hidden = mode !== "2d";
  $("three").hidden = mode !== "3d";
  $("replaybar").hidden = mode !== "3d";
  if (mode === "3d") {
    if (!three) initThree();
    sizeThree();
    buildReplay();
  } else {
    drawMap();
  }
  saveHash();
}

function initThree() {
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(devicePixelRatio || 1);
  $("three").appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(css("--asphalt"));
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(-40, 80, 30);
  scene.add(sun);
  const camera = new THREE.PerspectiveCamera(40, 1, 0.5, 2000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI / 2.1;
  three = { renderer, scene, camera, controls, ground: null, actors: new THREE.Group(), marks: new THREE.Group(), last: performance.now() };
  scene.add(three.actors, three.marks);
  const caption = document.createElement("p");
  caption.className = "caption3d";
  caption.id = "caption3d";
  $("three").appendChild(caption);
  renderer.setAnimationLoop(tick);
}

function disposeTextures() {
  if (three?.ground) {
    three.scene.remove(three.ground);
    three.ground.material.map.dispose();
    three.ground = null;
  }
}

function sizeThree() {
  if (!three) return;
  const el = $("three").parentElement;
  three.renderer.setSize(el.clientWidth, el.clientHeight, false);
  three.camera.aspect = el.clientWidth / Math.max(el.clientHeight, 1);
  three.camera.updateProjectionMatrix();
}

const toScene = (x, y, h = 0) => new THREE.Vector3(x, h, -y);

function ensureGround() {
  if (three.ground) return;
  const m = st.view.map;
  const w = m.width * m.mpp_x, h = m.height * m.mpp_y;
  const tex = new THREE.Texture(st.img);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  tex.needsUpdate = true;
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshLambertMaterial({ map: tex }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.copy(toScene(m.x0 + w / 2, m.y0 - h / 2));
  three.scene.add(ground);
  three.ground = ground;
}

function clearGroup(g) {
  for (const o of [...g.children]) {
    g.remove(o);
    o.geometry?.dispose();
    o.material?.dispose();
  }
}

function buildReplay() {
  if (!three) return;
  ensureGround();
  clearGroup(three.actors);
  clearGroup(three.marks);
  const f = finding();
  const reps = f?.replays || [];
  $("event").innerHTML = reps.map((r, k) => `<option value="${k}">Conflict ${k + 1}: ${r.measure} ${fmt(r.value)} s, ${esc(users([r.cls_1, r.cls_2]))}</option>`).join("");
  $("event").value = String(st.replay);
  const r = reps[st.replay];
  if (!r) {
    $("caption3d").textContent = "No conflict replay for this hotspot.";
    return;
  }
  const pair = new Set([String(r.id_1), String(r.id_2)]);
  for (const u of r.users) {
    const hot = pair.has(String(u.id));
    const h = HEIGHT_M[u.cls] || 1.5;
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(Math.max(u.length, 0.4), h, Math.max(u.width, 0.4)),
      new THREE.MeshStandardMaterial({ color: hot ? css("--conflict") : COLOUR[u.cls] || "#cccccc", roughness: 0.6,
                                       emissive: hot ? css("--conflict") : "#000000", emissiveIntensity: hot ? 0.25 : 0 }));
    mesh.userData = { track: u.track, h };
    three.actors.add(mesh);
  }
  const half = f.cell_m / 2;
  const sq = [[-half, -half], [half, -half], [half, half], [-half, half], [-half, -half]].map(([dx, dy]) => toScene(f.x + dx, f.y + dy, 0.08));
  three.marks.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(sq), new THREE.LineBasicMaterial({ color: css("--marking") })));
  const link = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
    new THREE.LineBasicMaterial({ color: css("--conflict") }));
  link.userData.pair = [...pair];
  three.marks.add(link);
  three.link = link;
  three.controls.target.copy(toScene(f.x, f.y));
  three.camera.position.copy(toScene(f.x - 28, f.y - 34, 30));
  three.controls.update();
  $("caption3d").textContent = `${r.measure} ${fmt(r.value)} s, ${r.type.replace("_", "-")} conflict between a ${users([r.cls_1, r.cls_2]).replace(" and ", " and a ")} (red). ` +
    "Boxes are measured positions, lengths and widths; heights are schematic.";
  setTime(WINDOW[0]);
}

function sample(track, t) {
  if (!track.length || t < track[0][0] || t > track[track.length - 1][0]) return null;
  let lo = 0, hi = track.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (track[mid][0] <= t) lo = mid; else hi = mid; }
  const a = track[lo], b = track[hi];
  const u = b[0] > a[0] ? (t - a[0]) / (b[0] - a[0]) : 0;
  let dyaw = b[3] - a[3];
  dyaw = ((dyaw + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
  return [a[1] + u * (b[1] - a[1]), a[2] + u * (b[2] - a[2]), a[3] + u * dyaw];
}

function setTime(t) {
  st.t = Math.min(Math.max(t, WINDOW[0]), WINDOW[1]);
  $("time").value = st.t;
  $("tlabel").textContent = `${st.t >= 0 ? "+" : ""}${st.t.toFixed(1)} s`;
  if (!three) return;
  const pos = {};
  three.actors.children.forEach((m, k) => {
    const p = sample(m.userData.track, st.t);
    m.visible = !!p;
    if (p) {
      m.position.copy(toScene(p[0], p[1], m.userData.h / 2));
      m.rotation.y = p[2];
      pos[k] = m.position;
    }
  });
  const f = finding();
  const r = f?.replays?.[st.replay];
  if (r && three.link) {
    const idx = r.users.map((u) => String(u.id));
    const a = pos[idx.indexOf(String(r.id_1))], b = pos[idx.indexOf(String(r.id_2))];
    three.link.visible = !!(a && b);
    if (a && b) three.link.geometry.setFromPoints([a.clone().setY(a.y * 2 + 0.2), b.clone().setY(b.y * 2 + 0.2)]);
  }
}

function tick(now) {
  const dt = Math.min((now - three.last) / 1000, 0.1);
  three.last = now;
  if (st.mode !== "3d") return;
  if (st.playing) setTime(st.t + dt >= WINDOW[1] ? WINDOW[0] : st.t + dt);
  three.controls.update();
  three.renderer.render(three.scene, three.camera);
}

/* ---------- review panel ---------- */

function renderPanel() {
  const p = st.view.panel;
  if (!p) {
    $("panel").innerHTML = `<p class="empty">The review panel has not run on this audit. Run <code>nml panel ${esc(st.view.split)}</code>.</p>`;
    return;
  }
  const role = { proposer: "Proposer", skeptic: "Skeptic", judge: "Judge" };
  let h = `<div class="stages">${p.stages.map((s) => `<div class="stagecard ${s.accepted ? "ok" : ""}"><h3>${role[s.role] || esc(s.role)}</h3>` +
    `<p class="meta">${esc(s.model)}, ${s.turns} turns, $${fmt(s.usd, 4)}. ${s.accepted ? "Accepted by the checker." : `Stopped: ${esc(s.stopped)}.`}</p>` +
    (s.caught.length ? `<ul class="caught">${s.caught.map((e) => `<li>Rejected: ${esc(e)}</li>`).join("")}</ul>` : "") + "</div>").join("")}</div>`;
  if (p.decisions) {
    const name = Object.fromEntries(p.proposals.map((x) => [`${x.rank}:${x.crfid}`, x.psc]));
    h += `<table><thead><tr><th>Hotspot</th><th>Countermeasure</th><th>CMF</th><th>Decision</th><th>Reason</th></tr></thead><tbody>${
      p.decisions.map((d) => `<tr><td>${d.rank}</td><td>${esc(name[`${d.rank}:${d.crfid}`])}</td><td>${esc(d.crfid)}</td>` +
        `<td class="${d.accept ? "decision-accept" : "decision-reject"}">${d.accept ? "Accept" : "Reject"}</td><td>${esc(d.reason)}</td></tr>`).join("")}</tbody></table>`;
  }
  if (p.objections?.length) {
    h += `<details><summary>Skeptic's objections (${p.objections.length})</summary><ul>${p.objections.map((o) =>
      `<li>Hotspot ${o.rank}${o.crfid ? `, CMF ${esc(o.crfid)}` : ""}${o.blocking ? " (blocking)" : ""}: ${esc(o.objection)}</li>`).join("")}</ul></details>`;
  }
  if (p.memo) h += `<h3>Judge's memo</h3><div class="memo">${md(p.memo)}</div>`;
  $("panel").innerHTML = h;
}

/* ---------- complaints ---------- */

function renderVoice() {
  const v = st.view.voice;
  if (!v) {
    $("voice").innerHTML = `<p class="empty">No complaints have been checked for this audit. Run <code>nml voice ${esc(st.view.split)}</code>, or add <code>--audio</code> with a recording.</p>`;
    return;
  }
  const s = v.summary;
  let h = s.match_accuracy !== undefined
    ? `<p>Test on ${s.recordings} synthetic complaints spoken by Meta MMS-TTS from the audit's own hotspots, plus a decoy no hotspot shows: ` +
      `${s.correct} of ${s.recordings} matched correctly, mean word error rate ${fmt(s.mean_word_error_rate * 100, 0)}%. These are test recordings, not residents' reports.</p>`
    : "";
  h += `<div class="stages">${v.results.map((r) => {
    const m = r.match;
    const verdict = m.rank ? `Matches hotspot ${m.rank}: ${esc(m.evidence.join(", "))}.` : "No hotspot in this audit shows it.";
    const check = r.synthetic ? `<p class="meta">Built from ${esc(r.source)}, spoken in ${esc(r.lang)}. ${r.correct ? "Correct." : "Wrong."} Word error rate ${fmt(r.word_error_rate * 100, 0)}%.</p>` : "";
    return `<div class="stagecard ${m.rank ? "ok" : ""}"><p>“${esc(r.transcript)}”</p><p class="meta">${esc(r.complaint.concern)}</p><p><strong>${verdict}</strong></p>${check}</div>`;
  }).join("")}</div>`;
  $("voice").innerHTML = h;
}

/* ---------- signals ---------- */

function renderSignals() {
  const rows = st.view.signal_entry || [];
  if (!rows.length) {
    $("signals").innerHTML = '<p class="empty">No signal log for this site.</p>';
    return;
  }
  const col = { G: css("--go"), y: css("--amber"), r: css("--conflict") };
  const arm = { N: "north", E: "east", S: "south", W: "west" };
  let h = `<p class="legend">${["G", "y", "r"].map((k) => `<span class="swatch" style="background:${col[k]}"></span>${SIGNAL[k]}`).join("")}</p><div class="bars">`;
  for (const r of rows) {
    const n = r.G + r.y + r.r;
    h += `<span class="lab">From ${arm[r.arm] || r.arm}, ${NAME[r.cls] || r.cls}s</span><span class="bar" role="img" aria-label="${r.G} green, ${r.y} yellow, ${r.r} red of ${n}">` +
      ["G", "y", "r"].map((k) => `<span style="width:${(100 * r[k]) / n}%;background:${col[k]}"></span>`).join("") +
      `</span><span class="val">${((100 * r.r) / n).toFixed(0)}% red (n=${n})</span>`;
  }
  $("signals").innerHTML = h + "</div>";
}

/* ---------- scorecard ---------- */

function renderScore() {
  const rows = st.index.selftest || [];
  $("score").innerHTML = rows.length
    ? `<table><thead><tr><th>Check</th><th>Status</th><th>Criterion</th></tr></thead><tbody>${rows.map((r) =>
        `<tr><td>${esc(r.check.replace("_", " "))}</td><td class="status ${esc(r.status)}">${esc(r.status)}</td><td>${esc(r.criterion)}` +
        `<details><summary>Result</summary><pre>${esc(JSON.stringify(r.result, null, 1))}</pre></details></td></tr>`).join("")}</tbody></table>`
    : '<p class="empty">No self-test report found. Run <code>nml selftest</code>.</p>';
  $("results").innerHTML = st.index.results_md ? md(st.index.results_md) : "";
}

init().catch((e) => {
  $("rail").innerHTML = `<p class="empty">Could not load the audit data: ${esc(e.message)}. Serve this folder over HTTP, for example with <code>python -m http.server -d docs</code>.</p>`;
});
