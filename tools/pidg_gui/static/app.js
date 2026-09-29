"use strict";
// PiDG web GUI. Talks to pidg_gui.py (same origin) over a small JSON API; every value
// shown comes from the board's own STATUS reply (realized cycles), never from local math
// on the requested values.

const $ = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";

// ---------------------------------------------------------------- field metadata
const META = {
  FREQ: { group: "laser", label: "Pair rate", kind: "hz", help: "pulse pairs per second" },
  WIDTH: { group: "laser", label: "Pulse width", kind: "ns", help: "both laser pulses" },
  DELAY: { group: "laser", label: "Δt (CH2 delay)", kind: "ns", help: "CH2 rise after CH1 rise" },
  COMBINE: { group: "laser", label: "Outputs", kind: "select",
    options: [[0, "Split"], [1, "Combined"]] },  // the realized line spells out the routing
  MARKERWIDTH: { group: "camera", label: "Marker width", kind: "ns" },
  PIXGATE: { group: "pix", label: "Gate", kind: "select",
    options: [[0, "Off (J12 only)"], [1, "While ARMED"], [2, "Always"]] },
  PIXLEAD: { group: "pix", label: "Release before CH1", kind: "ns" },
  PIXLAG: { group: "pix", label: "Reset after last pulse", kind: "ns" },
};
const GROUP_BOX = { laser: "laserFields", camera: "cameraFields", pix: "pixFields", other: "otherFields" };
// Shown read-only, never set from the page (the server refuses other values too).
const FIXED = { SYNC: 1000000 };

let snap = null;        // last /api/state reply
let dirty = {};         // NAME -> text typed by the user, not yet applied
let fitMode = "pulses";
let logSeq = 0;
let polling = false;

// ---------------------------------------------------------------- units
function parseWithUnits(text, kind) {
  const s = String(text).trim().replace(/,/g, "").replace(/\s+/g, "");
  if (kind === "count" || kind === "select") {
    if (!/^\d+$/.test(s)) throw new Error("whole number");
    return parseInt(s, 10);
  }
  const m = /^(\d+(?:\.\d*)?|\.\d+)([a-zA-Zµ]*)$/.exec(s);
  if (!m) throw new Error(kind === "ns" ? "e.g. 10000, 10us, 2.5 ms" : "e.g. 1000, 20k, 1 MHz");
  const v = parseFloat(m[1]);
  const u = m[2].toLowerCase().replace("µ", "u");
  const scale = kind === "ns"
    ? { "": 1, ns: 1, us: 1e3, ms: 1e6, s: 1e9 }[u]
    : { "": 1, hz: 1, k: 1e3, khz: 1e3, m: 1e6, mhz: 1e6 }[u];
  if (scale === undefined) throw new Error(kind === "ns" ? "unit ns, us, ms or s" : "unit Hz, kHz or MHz");
  const r = Math.round(v * scale);
  if (r > 4294967295) throw new Error("too large");
  return r;
}

function fmtTime(sec, digits = 3) {
  const a = Math.abs(sec);
  if (a === 0) return "0 s";
  const [scale, unit] = a < 1e-6 ? [1e9, "ns"] : a < 1e-3 ? [1e6, "µs"] : a < 1 ? [1e3, "ms"] : [1, "s"];
  return (sec * scale).toFixed(digits).replace(/\.?0+$/, "") + " " + unit;
}
function fmtNsExact(cycles, clk) { return (cycles * 1e9 / clk).toFixed(3) + " ns"; }
function fmtHz(hz) {
  if (hz >= 1e6) return (hz / 1e6).toFixed(6).replace(/\.?0+$/, "") + " MHz";
  if (hz >= 1e3) return (hz / 1e3).toFixed(6).replace(/\.?0+$/, "") + " kHz";
  return hz.toFixed(3).replace(/\.?0+$/, "") + " Hz";
}

// ---------------------------------------------------------------- API
async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({ error: "bad reply from the GUI server" }));
  if (!r.ok && !j.state) throw new Error(j.error || r.statusText);
  return j;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 2200);
}

// ---------------------------------------------------------------- connection
async function loadPorts() {
  const sel = $("target");
  const keep = sel.value;
  let info = { ports: [], sim: false };
  try { info = await api("/api/ports"); } catch (e) { /* server not reachable */ }
  sel.replaceChildren();
  for (const p of info.ports) {
    const o = document.createElement("option");
    o.value = p.device;
    o.textContent = p.device + (p.pidg ? " — PiDG" : p.description ? " — " + p.description : "");
    sel.appendChild(o);
  }
  if (info.sim) sel.appendChild(new Option("Simulator (no hardware)", "sim"));
  sel.appendChild(new Option("Other port or URL…", "__custom"));
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
  $("customTarget").hidden = sel.value !== "__custom";
}

async function toggleConnect() {
  const btn = $("connectBtn");
  btn.disabled = true;
  try {
    if (snap && snap.connected) {
      snap = await api("/api/disconnect", {});
    } else {
      let target = $("target").value;
      if (target === "__custom") target = $("customTarget").value.trim();
      if (!target) throw new Error("choose a port");
      snap = await api("/api/connect", { target });
      logSeq = 0;
      $("console").replaceChildren();
      dirty = {};
    }
  } catch (e) {
    toast(String(e.message || e));
  }
  btn.disabled = false;
  render();
}

// ---------------------------------------------------------------- polling
async function poll() {
  if (polling) return;
  polling = true;
  try {
    snap = await api("/api/state");
    render();
    if (snap.connected) {
      const lg = await api("/api/log?since=" + logSeq);
      appendLog(lg.entries || []);
      logSeq = lg.next || logSeq;
    }
  } catch (e) {
    snap = { connected: false, error: "GUI server not reachable" };
    render();
  } finally {
    polling = false;
  }
}

// ---------------------------------------------------------------- arming
let armConfirmUntil = 0;
async function armClicked() {
  const btn = $("armBtn");
  if (Date.now() > armConfirmUntil) {
    armConfirmUntil = Date.now() + 3000;
    btn.textContent = "Click again to ARM";
    btn.classList.add("confirm");
    setTimeout(() => { if (Date.now() > armConfirmUntil) { btn.textContent = "ARM"; btn.classList.remove("confirm"); } }, 3100);
    return;
  }
  armConfirmUntil = 0;
  btn.textContent = "ARM";
  btn.classList.remove("confirm");
  try {
    const r = await api("/api/arm", {});
    toast(r.reply || r.error);
    if (r.state) snap = r.state;
  } catch (e) { toast(String(e.message || e)); }
  render();
}

async function disarm(src) {
  if (!snap || !snap.connected) return;
  try {
    const r = await api("/api/disarm", {});
    toast((r.ok ? "Disarmed" : "DISARM not confirmed: " + (r.reply || r.error)) + (src ? " (" + src + ")" : ""));
    if (r.state) snap = r.state;
  } catch (e) { toast("DISARM failed: " + (e.message || e) + " — use the hardware E-stop"); }
  render();
}

// ---------------------------------------------------------------- settings
function fieldRow(name) {
  let row = document.querySelector('.field[data-name="' + name + '"]');
  if (row) return row;
  const meta = META[name] || { group: "other", label: name, kind: "count" };
  row = document.createElement("div");
  row.className = "field";
  row.dataset.name = name;
  const label = document.createElement("label");
  const id = "f_" + name;
  label.htmlFor = id;
  label.textContent = meta.label;
  const code = document.createElement("span");
  code.className = "code";
  code.textContent = name;
  label.appendChild(code);
  const wrap = document.createElement("div");
  wrap.className = "input";
  let input;
  if (meta.kind === "select") {
    input = document.createElement("select");
    for (const [v, t] of meta.options) input.appendChild(new Option(t, String(v)));
  } else {
    input = document.createElement("input");
    input.type = "text";
    input.inputMode = "decimal";
    input.autocomplete = "off";
    input.spellcheck = false;
  }
  input.id = id;
  const unit = document.createElement("span");
  unit.className = "unit";
  unit.textContent = meta.unit || (meta.kind === "ns" ? "ns" : meta.kind === "hz" ? "Hz" : "");
  wrap.append(input);
  const realized = document.createElement("div");
  realized.className = "realized";
  const err = document.createElement("div");
  err.className = "error";
  if (meta.kind === "select") { row.classList.add("wide"); row.append(label, wrap, realized, err); }
  else row.append(label, wrap, unit, realized, err);
  const markDirty = () => {
    dirty[name] = input.value;
    row.classList.add("dirty");
    err.textContent = "";
    if (meta.kind === "ns" || meta.kind === "hz") {
      try {
        const v = parseWithUnits(input.value, meta.kind);
        realized.textContent = "→ " + v.toLocaleString("en-US") + (meta.kind === "ns" ? " ns" : " Hz") + " (press Enter or Apply)";
      } catch (e) { realized.textContent = e.message; }
    }
  };
  input.addEventListener("input", markDirty);
  input.addEventListener("change", markDirty);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); applyNames([name]); }
  });
  $(GROUP_BOX[meta.group] || "otherFields").appendChild(row);
  return row;
}

function realizedText(name, f, clk) {
  if (f.mode) return f.mode;
  if (f.unit === "ns" && f.cycles !== undefined) {
    return "actual " + f.actual.toFixed(3) + " ns · " + f.cycles.toLocaleString("en-US") + " cycles" +
      (f.actual >= 1000 ? " (" + fmtTime(f.actual * 1e-9) + ")" : "");
  }
  if (f.unit === "Hz" && f.cycles !== undefined) {
    return "actual " + f.actual.toFixed(3) + " Hz · period " + fmtTime(f.cycles / clk, 6);
  }
  if (f.unit === "Hz" && f.divider !== undefined) {
    return "actual " + fmtHz(f.actual) + " · divider " + f.divider.toFixed(3) + (f.jitter ? " (1-cycle jitter)" : "");
  }
  return f.detail || "";
}

async function applyNames(names) {
  const settings = {};
  for (const n of names) {
    if (!(n in dirty)) continue;
    const row = fieldRow(n);
    const meta = META[n] || { kind: "count" };
    try {
      settings[n] = parseWithUnits(dirty[n], meta.kind);
    } catch (e) {
      row.querySelector(".error").textContent = n + ": " + e.message;
      return;
    }
  }
  if (!Object.keys(settings).length) { toast("Nothing changed"); return; }
  try {
    const r = await api("/api/apply", { settings });
    if (r.error) toast(r.error);
    for (const res of r.results || []) {
      const row = fieldRow(res.name);
      if (res.ok) {
        delete dirty[res.name];
        row.classList.remove("dirty");
        row.querySelector(".error").textContent = "";
      } else {
        row.querySelector(".error").textContent = res.reply;
      }
    }
    if (r.state) snap = r.state;
  } catch (e) { toast(String(e.message || e)); }
  render();
}

function applyGroup(group) {
  applyNames(Object.keys(dirty).filter((n) => ((META[n] || {}).group || "other") === group));
}

// ---------------------------------------------------------------- rendering
function render() {
  const connected = !!(snap && snap.connected);
  document.body.classList.toggle("disconnected", !connected);
  $("connectBtn").textContent = connected ? "Disconnect" : "Connect";
  $("target").disabled = connected;
  $("customTarget").disabled = connected;
  $("ident").textContent = connected ? (snap.identity || snap.target) : (snap && snap.error ? snap.error : "Not connected");
  $("ident").title = $("ident").textContent;
  for (const b of document.querySelectorAll("#armBtn, .apply, #cmdSend")) b.disabled = !connected;
  for (const b of document.querySelectorAll(".disarm")) b.disabled = !connected;

  const st = connected ? snap.status : null;
  const sys = st ? st.system : {};
  const pill = $("armPill");
  const pending = st ? parseInt(sys.START_PENDING_US || "0", 10) : 0;
  pill.className = "pill" + (st && sys.ARMED ? (pending > 0 ? " pending" : " armed") : "");
  $("armText").textContent = !st ? (connected ? "…" : "offline")
    : sys.ARMED ? (pending > 0 ? "ARMED · starting in " + fmtTime(pending * 1e-6, 0) : "ARMED") : "DISARMED";

  if (!st) {
    if (connected && snap.error) $("ident").textContent = snap.error;
    renderSysline(null);
    renderCharts(null);
    return;
  }
  const clk = parseInt(sys.CLK || "150000000", 10);
  for (const name of st.order) {
    if (name in FIXED) continue;
    const row = fieldRow(name);
    const f = st.fields[name];
    const input = row.querySelector("input, select");
    if (!(name in dirty) && document.activeElement !== input) {
      input.value = String(f.value);
      row.querySelector(".realized").textContent = realizedText(name, f, clk);
    } else if (!(name in dirty)) {
      row.querySelector(".realized").textContent = realizedText(name, f, clk);
    }
  }
  $("pixCard").hidden = !st.fields.PIXGATE;
  $("otherCard").hidden = !$("otherFields").children.length;
  if (st.pixreset) {
    $("pixSummary").textContent = st.pixreset.on
      ? "Pixels free " + fmtTime(st.pixreset.free_ns * 1e-9) + " around each pair, in reset " + fmtTime(st.pixreset.reset_ns * 1e-9) + " per period (from CH1 + " + fmtTime(st.pixreset.start_ns * 1e-9) + ")."
      : "Gate off: the pixel reset follows the J12 input only.";
  }
  kv($("armInfo"), [
    ["Firmware", sys.ARMED ? "ARMED" : "DISARMED"],
    ["Start hold-off", pending > 0 ? fmtTime(pending * 1e-6, 0) : "none"],
    ["Hardware", sys.HW || "?"],
  ]);
  renderSysline(sys, clk, st.fields.SYNC);
  renderCharts(st, clk);
}

// The board's system keys, compact, under the identity in the header. A watchdog reset,
// dropped replies or a sync clock other than 1 MHz (set outside this page; the cameras'
// timestamps would be scaled) are flagged.
function renderSysline(sys, clk, sync) {
  const box = $("sysline");
  box.replaceChildren();
  if (!sys) return;
  const wdtResets = parseInt(sys.WDT_RESETS || "0", 10), dropped = parseInt(sys.TX_DROPPED || "0", 10);
  const items = [];
  if (sync && sync.value !== FIXED.SYNC) {
    items.push(["sync " + fmtHz(sync.actual) + ", not 1 MHz: send SYNC 1000000 in the console, or reset the board", true]);
  }
  items.push(
    [fmtHz(clk) + " clock (" + (1e9 / clk).toFixed(3) + " ns steps)", false],
    ["last reset " + (sys.RESET || "?"), sys.RESET === "WATCHDOG"],
  );
  if (wdtResets > 0) items.push([wdtResets + " watchdog reset" + (wdtResets > 1 ? "s" : "") + " since power-on", true]);
  items.push(["watchdog " + (parseInt(sys.WDT_MS || "0", 10) / 1000) + " s", false]);
  items.push([dropped > 0 ? dropped.toLocaleString("en-US") + " reply bytes dropped" : "no replies dropped", dropped > 0]);
  items.forEach(([text, warn], i) => {
    if (i) box.append(" · ");
    const s = document.createElement("span");
    s.textContent = (warn ? "⚠ " : "") + text;
    if (warn) s.className = "warn";
    box.append(s);
  });
  box.title = box.textContent;
}

function kv(dl, pairs) {
  dl.replaceChildren();
  for (const [k, v] of pairs) {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    dl.append(dt, dd);
  }
}

function appendLog(entries) {
  const box = $("console");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
  for (const e of entries) {
    const div = document.createElement("div");
    div.className = e.dir === ">" ? "in" : e.text.startsWith("ERR") ? "err" : "out";
    div.textContent = (e.dir === ">" ? "> " : "  ") + e.text;
    box.appendChild(div);
  }
  while (box.children.length > 1500) box.removeChild(box.firstChild);
  if (atBottom) box.scrollTop = box.scrollHeight;
}

async function sendCommand() {
  const inp = $("cmdInput");
  const line = inp.value.trim();
  if (!line) return;
  inp.value = "";
  try {
    const r = await api("/api/command", { line });
    if (r.error) toast(r.error);
    if (r.state) snap = r.state;
  } catch (e) {  // refused by the GUI server, or the server is unreachable
    appendLog([{ dir: ">", text: line }, { dir: "<", text: "ERR " + (e.message || e) }]);
  }
  render();
  const lg = await api("/api/log?since=" + logSeq).catch(() => null);
  if (lg) { appendLog(lg.entries || []); logSeq = lg.next || logSeq; }
}

// ---------------------------------------------------------------- timing model
function timingModel(st, clk) {
  const f = st.fields, sys = st.system;
  const c = (k) => (f[k] && f[k].cycles !== undefined ? f[k].cycles : 0);
  const m = {
    clk, P: c("FREQ"), W: c("WIDTH"), D: c("DELAY"), MW: c("MARKERWIDTH"),
    combine: f.COMBINE ? f.COMBINE.value : 0,
    gate: f.PIXGATE ? f.PIXGATE.value : null,
    L: c("PIXLEAD"), G: c("PIXLAG"),
    armed: !!sys.ARMED,
  };
  m.s = (cyc) => cyc / clk;  // cycles -> seconds
  return m;
}

// The rows of the diagram for pairs k0..k1 (pair k starts at k x period).
function buildRows(m, k0, k1) {
  const P = m.s(m.P), W = m.s(m.W), D = m.s(m.D), MW = m.s(m.MW), L = m.s(m.L), G = m.s(m.G);
  const ch1 = [], ch2 = [], mk = [], free = [];
  for (let k = k0; k <= k1; k++) {
    const t = k * P;
    ch1.push([t, t + W]);
    ch2.push([t + D, t + D + W]);
    mk.push([t, t + MW]);
    free.push([t - L, t + D + W + G]);
  }
  const l1 = m.combine ? ch1.concat(ch2) : ch1;
  const l2 = m.combine ? ch2.concat(ch1) : ch2;
  const lasersNote = m.armed ? "" : "Laser outputs are held LOW while DISARMED (drawn faint): the timing shown is what ARM will produce.";
  const rows = [
    { name: "Laser 1", sub: "J7" + (m.combine ? " · both pulses" : " · CH1"), color: 1, highs: l1, inactive: !m.armed, note: lasersNote, state: ["LOW", "HIGH"] },
    { name: "Laser 2", sub: "J8" + (m.combine ? " · both pulses" : " · CH2"), color: 2, highs: l2, inactive: !m.armed, note: lasersNote, state: ["LOW", "HIGH"] },
    { name: "Marker", sub: "J10 MKR", color: 3, highs: mk, state: ["LOW", "HIGH"] },
  ];
  if (m.gate !== null) {
    const on = m.gate > 0;
    rows.push({
      name: "Pixel reset", sub: "TDRSTN · low = reset", color: 4, washLow: on,
      highs: on ? free : [[-1e9, 1e9]],
      inactive: on && m.gate === 1 && !m.armed,
      note: !on ? "Pixel-reset gate off: TDRSTN follows the J12 input only." : m.gate === 1 && !m.armed ? "The pixel-reset gate (PIXGATE 1) runs only while ARMED (drawn faint)." : "",
      state: ["reset", "free"],
    });
  }
  return rows;
}

// ---------------------------------------------------------------- charts
function el(tag, attrs, parent) {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
function txt(parent, x, y, s, cls, anchor) {
  const t = el("text", { x, y, class: cls, "text-anchor": anchor || "start" }, parent);
  t.textContent = s;
  return t;
}
function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * p;
}
function axisUnit(span) {
  return span < 2e-6 ? [1e9, "ns"] : span < 2e-3 ? [1e6, "µs"] : span < 2 ? [1e3, "ms"] : [1, "s"];
}
function mergeClip(intervals, t0, t1) {
  const v = intervals.map(([a, b]) => [Math.max(a, t0), Math.min(b, t1)]).filter(([a, b]) => b > a).sort((p, q) => p[0] - q[0]);
  const out = [];
  for (const iv of v) {
    if (out.length && iv[0] <= out[out.length - 1][1]) out[out.length - 1][1] = Math.max(out[out.length - 1][1], iv[1]);
    else out.push(iv.slice());
  }
  return out;
}

function drawChart(box, m, rows, t0, t1, opts) {
  const W = Math.max(320, box.clientWidth || 800);
  const left = 150, right = 16, top = opts.top || 22, rowH = 46, amp = 22, axisH = 26;
  const H = top + rows.length * rowH + axisH;
  const plotW = W - left - right;
  const X = (t) => left + ((t - t0) / (t1 - t0)) * plotW;
  const svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img", "aria-label": opts.aria });
  let widened = false;

  // time grid + axis
  const span = t1 - t0;
  const [us, un] = axisUnit(span);
  const step = niceStep(span / Math.max(2, plotW / 95));
  for (let t = Math.ceil(t0 / step) * step; t <= t1 + step * 1e-9; t += step) {
    const x = X(t);
    el("line", { x1: x, x2: x, y1: top - 6, y2: H - axisH, class: "grid-line" }, svg);
    const v = Math.abs(t) < step * 1e-6 ? 0 : t * us;
    txt(svg, x, H - axisH + 16, (+v.toPrecision(6)).toString() + (x > W - 80 ? " " + un : ""), "tick", "middle");
  }
  el("line", { x1: left, x2: W - right, y1: H - axisH, y2: H - axisH, class: "axis-line" }, svg);
  txt(svg, left - 8, H - axisH + 16, un, "tick", "end");

  (opts.decorate || (() => {}))(svg, X, top);

  rows.forEach((r, i) => {
    const yLo = top + i * rowH + rowH - 12, yHi = yLo - amp;
    const color = "var(--series-" + r.color + ")";
    // row label + line key (the key carries the colour; the text stays in ink)
    el("line", { x1: 8, x2: 22, y1: yLo - amp / 2, y2: yLo - amp / 2, stroke: color, "stroke-width": 2, "stroke-linecap": "round" }, svg);
    txt(svg, 28, yLo - amp / 2 - 2, r.name, "row-label");
    txt(svg, 28, yLo - amp / 2 + 12, r.sub, "row-sub");
    const g = el("g", { class: r.inactive ? "inactive" : "" }, svg);
    const highs = mergeClip(r.highs, t0, t1);
    // change points
    let level = highs.length && highs[0][0] <= t0 ? 1 : 0;
    let d = "M" + X(t0) + " " + (level ? yHi : yLo);
    let lastX = X(t0);
    const washes = [];
    for (const [a, b] of highs) {
      let xa = Math.max(X(a), lastX), xb = X(b);
      if (a > t0) { d += " H" + xa + " V" + yHi; }
      if (b < t1) {
        if (xb - xa < 2) { xb = xa + 2; widened = true; }
        d += " H" + xb + " V" + yLo;
      } else xb = X(t1);
      washes.push([xa, xb]);
      lastX = xb;
    }
    d += " H" + X(t1);
    if (r.washLow) {  // shade the asserted (reset = low) state
      let prev = X(t0);
      for (const [xa, xb] of washes) { if (xa > prev) el("rect", { x: prev, y: yHi, width: xa - prev, height: amp, fill: color, class: "wash" }, g); prev = xb; }
      if (X(t1) > prev) el("rect", { x: prev, y: yHi, width: X(t1) - prev, height: amp, fill: color, class: "wash" }, g);
    } else {
      for (const [xa, xb] of washes) el("rect", { x: xa, y: yHi, width: Math.max(xb - xa, 0), height: amp, fill: color, class: "wash" }, g);
    }
    el("path", { d, stroke: color, class: "wave" }, g);
    const hs = r.highs;
    r.level = (t) => (hs.some(([a, b]) => t >= a && t < b) ? 1 : 0);
    r.y = [yHi, yLo];
  });

  (opts.annotate || (() => {}))(svg, X, rows, top, rowH);

  // hover: crosshair + one tooltip for every row
  const hair = el("line", { y1: top - 6, y2: H - axisH, class: "crosshair", visibility: "hidden" }, svg);
  const hit = el("rect", { x: left, y: 0, width: plotW, height: H - axisH, class: "hit" }, svg);
  const tip = document.createElement("div");
  tip.className = "tooltip";
  tip.hidden = true;
  const move = (ev) => {
    const rect = svg.getBoundingClientRect();
    const x = (ev.clientX - rect.left) * (W / rect.width);
    const t = t0 + ((x - left) / plotW) * (t1 - t0);
    hair.setAttribute("x1", x); hair.setAttribute("x2", x); hair.setAttribute("visibility", "visible");
    tip.replaceChildren();
    const head = document.createElement("div");
    head.className = "t";
    head.textContent = opts.timeLabel(t);
    tip.appendChild(head);
    for (const r of rows) {
      const line = document.createElement("div"); line.className = "r";
      const key = document.createElement("span"); key.className = "key"; key.style.background = "var(--series-" + r.color + ")";
      const v = document.createElement("span"); v.className = "v"; v.textContent = r.state[r.level(t)] || "";
      const n = document.createElement("span"); n.className = "n"; n.textContent = r.name;
      line.append(key, v, n);
      tip.appendChild(line);
    }
    tip.hidden = false;
    const bx = box.getBoundingClientRect();
    const px = ev.clientX - bx.left, py = ev.clientY - bx.top;
    tip.style.left = Math.min(px + 14, bx.width - 190) + "px";
    tip.style.top = Math.max(0, py - 20) + "px";
  };
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerleave", () => { tip.hidden = true; hair.setAttribute("visibility", "hidden"); });

  box.replaceChildren(svg, tip);
  return widened;
}

function dimension(svg, x0, x1, y, label, W) {
  if (x1 - x0 < 12) {  // too narrow for a bracket: a label beside the mark
    if (x1 + label.length * 6.2 + 8 < W - 10) txt(svg, x1 + 6, y + 4, label, "dim-text");
    else txt(svg, x0 - 6, y + 4, label, "dim-text", "end");
    return;
  }
  el("path", { d: "M" + x0 + " " + (y - 4) + " V" + (y + 4) + " M" + x0 + " " + y + " H" + x1 + " M" + x1 + " " + (y - 4) + " V" + (y + 4), class: "dim" }, svg);
  const tw = label.length * 6.2;
  if (x1 - x0 > tw + 8) txt(svg, (x0 + x1) / 2, y - 5, label, "dim-text", "middle");
  else if (x1 + tw + 6 < W - 10) txt(svg, x1 + 5, y + 4, label, "dim-text");
  else txt(svg, x0 - 5, y + 4, label, "dim-text", "end");
}

function renderCharts(st, clk) {
  if (!st || !st.fields.FREQ || !st.fields.FREQ.cycles) {
    $("pairChart").replaceChildren();
    $("seqChart").replaceChildren();
    $("chartNote").textContent = st ? "" : "Connect to a PiDG (or the simulator) to see its timing.";
    $("edgeTable").tBodies[0].replaceChildren();
    return;
  }
  const m = timingModel(st, clk);
  const P = m.s(m.P), W = m.s(m.W), D = m.s(m.D), L = m.s(m.L), G = m.s(m.G);
  const lastFall = Math.max(W, D + W);
  const gateOn = m.gate !== null && m.gate > 0;
  $("fitWindow").disabled = !gateOn;
  const useWindow = gateOn && fitMode === "window";
  let t0 = useWindow ? -L : 0, t1 = useWindow ? lastFall + G : lastFall;
  const pad = (t1 - t0) * 0.12 || W;
  t0 -= pad; t1 += pad;
  $("timingSub").textContent = "Δt " + fmtTime(D, 3) + " · pulse " + fmtTime(W, 3) + " · " + fmtHz(clk / m.P) +
    " (period " + fmtTime(P, 3) + ")" + (m.combine ? " · combined outputs" : "") + ". Time 0 = CH1 rising edge; realized values.";

  const pairRows = buildRows(m, -1, 1);
  const w1 = drawChart($("pairChart"), m, pairRows, t0, t1, {
    top: 26,
    aria: "Timing of one pulse pair",
    timeLabel: (t) => "t = " + fmtTime(t, 3) + " after CH1",
    annotate: (svg, X, rows) => {
      const Wpx = svg.viewBox.baseVal.width;
      const r1 = rows[0], r2 = rows[1];
      dimension(svg, X(0), X(W), r1.y[0] - 8, "WIDTH " + fmtTime(W, 3), Wpx);
      dimension(svg, X(0), X(D), r2.y[0] - 8, "Δt " + fmtTime(D, 3), Wpx);
      const px = rows.find((r) => r.name === "Pixel reset");
      if (px && gateOn) {
        if (X(-L) > X(t0)) dimension(svg, X(-L), X(0), px.y[0] - 8, "PIXLEAD " + fmtTime(L, 3), Wpx);
        if (X(lastFall + G) < X(t1)) dimension(svg, X(lastFall), X(lastFall + G), px.y[0] - 8, "PIXLAG " + fmtTime(G, 3), Wpx);
      }
    },
  });

  // sequence: three pairs
  const K = 3;
  const s0 = (gateOn ? -L : 0) - 0.06 * P, s1 = (K - 1) * P + Math.max(lastFall + (gateOn ? G : 0), P * 0.35) + 0.06 * P;
  $("seqTitle").textContent = "Sequence: " + K + " consecutive pairs (period " + fmtTime(P, 3) + ")";
  const seqRows = buildRows(m, -1, K);
  const w2 = drawChart($("seqChart"), m, seqRows, s0, s1, {
    top: 22,
    aria: "Timing of three consecutive pulse pairs",
    timeLabel: (t) => {
      const k = Math.floor((t + P * 0.5) / P);
      return "t = " + fmtTime(t, 3) + " · pair " + (k + 1) + (Math.abs(t - k * P) > 0 ? " " + (t - k * P >= 0 ? "+" : "−") + fmtTime(Math.abs(t - k * P), 3) : "");
    },
    decorate: (svg, X, top) => {
      for (let k = 0; k < K; k++) txt(svg, X(k * P) + 3, top - 10, "pair " + (k + 1), "note");
    },
  });
  const notes = [];
  for (const r of pairRows) if (r.note && !notes.includes(r.note)) notes.push(r.note);
  if (w1 || w2) notes.push("Pulses narrower than 2 px are drawn 2 px wide.");
  if (m.combine) notes.push("COMBINE 1: both lasers carry CH1's and CH2's pulse.");
  $("chartNote").textContent = notes.join(" ");
  renderEdges(m);
}

function renderEdges(m) {
  const rows = [
    [1, "Laser 1", "rise", 0], [1, "Laser 1", "fall", m.W],
    [2, "Laser 2", "rise", m.D], [2, "Laser 2", "fall", m.D + m.W],
  ];
  if (m.combine) rows.push([1, "Laser 1", "rise (CH2)", m.D], [1, "Laser 1", "fall (CH2)", m.D + m.W], [2, "Laser 2", "rise (CH1)", 0], [2, "Laser 2", "fall (CH1)", m.W]);
  rows.push([3, "Marker", "rise", 0], [3, "Marker", "fall", m.MW]);
  if (m.gate) rows.push([4, "Pixel reset", "released (TDRSTN high)", -m.L], [4, "Pixel reset", "asserted (TDRSTN low)", Math.max(m.W, m.D + m.W) + m.G]);
  rows.push([1, "Next pair", "CH1 rise", m.P]);
  rows.sort((a, b) => a[3] - b[3]);
  const tb = $("edgeTable").tBodies[0];
  tb.replaceChildren();
  for (const [c, name, edge, cyc] of rows) {
    const tr = document.createElement("tr");
    const td1 = document.createElement("td");
    const sw = document.createElement("span"); sw.className = "swatch"; sw.style.background = "var(--series-" + c + ")";
    td1.append(sw, document.createTextNode(name));
    const td2 = document.createElement("td"); td2.textContent = edge;
    const td3 = document.createElement("td"); td3.className = "num"; td3.textContent = fmtNsExact(cyc, m.clk);
    const td4 = document.createElement("td"); td4.className = "num"; td4.textContent = cyc.toLocaleString("en-US");
    tr.append(td1, td2, td3, td4);
    tb.appendChild(tr);
  }
}

// ---------------------------------------------------------------- wiring
function remember(key, value) { try { localStorage.setItem("pidg." + key, value); } catch (e) { /* storage off */ } }
function recall(key) { try { return localStorage.getItem("pidg." + key); } catch (e) { return null; } }

const THEMES = ["auto", "light", "dark"];
function setTheme(t) {
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  $("themeBtn").title = "Colour theme: " + (t === "auto" ? "follows the system" : t);
  remember("theme", t);
}

function setFit(mode) {
  fitMode = mode;
  remember("fit", mode);
  $("fitPulses").setAttribute("aria-pressed", String(mode === "pulses"));
  $("fitWindow").setAttribute("aria-pressed", String(mode === "window"));
  render();
}

window.addEventListener("DOMContentLoaded", async () => {
  $("target").addEventListener("change", () => { $("customTarget").hidden = $("target").value !== "__custom"; });
  $("connectBtn").addEventListener("click", toggleConnect);
  $("refreshPorts").addEventListener("click", loadPorts);
  $("armBtn").addEventListener("click", armClicked);
  $("disarmBtn").addEventListener("click", () => disarm());
  $("disarmBtn2").addEventListener("click", () => disarm());
  $("fitPulses").addEventListener("click", () => setFit("pulses"));
  $("fitWindow").addEventListener("click", () => setFit("window"));
  for (const b of document.querySelectorAll(".apply")) b.addEventListener("click", () => applyGroup(b.dataset.group));
  $("cmdSend").addEventListener("click", sendCommand);
  $("cmdInput").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); sendCommand(); } });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") disarm("Esc");  // anywhere on the page, including inside a field
  });
  const q = new URLSearchParams(location.search);
  setTheme(q.get("theme") || recall("theme") || "auto");
  $("themeBtn").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "auto";
    setTheme(THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length]);
  });
  const fit = q.get("fit") || recall("fit");
  if (fit === "window" || fit === "pulses") setFit(fit);
  let resizeTimer = 0;
  new ResizeObserver(() => { clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 80); }).observe($("timingCard"));
  await loadPorts();
  await poll();
  setInterval(poll, 1000);
});
