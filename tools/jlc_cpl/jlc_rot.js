// JLC CPL rotation/centroid correction from JLC's own (LCSC/EasyEDA) footprints.
// For each placed part: fetch the LCSC part's EasyEDA Pro footprint, find the rotation R (0/90/180/270) and
// translation t that map its pads onto the KiCad footprint pads (KiCad footprint at orientation 0), then
// CPL rotation = board orientation + R and CPL position = board position + rotate(t, board orientation).
// Rotation convention: counter-clockwise as seen from the top, in a y-down frame (KiCad internal).
// Inputs: kpads.json (from kpads.py), fab/jlc BOM and CPL. Outputs: cpl_new.csv, rot_report.txt (here).
// Footprint downloads are cached in ./eda (git-ignored). Review rot_report.txt, then copy cpl_new.csv over the JLC CPL.
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const S = __dirname;
const DIR = path.join(S, '..', '..', 'Pico Version 4Layer') + '/';
const kp = JSON.parse(fs.readFileSync(path.join(S, 'kpads.json'), 'utf8'));

// ref -> LCSC from the JLC BOM
const bom = fs.readFileSync(DIR + 'fab/jlc/PiDG_Pico_JLC_BOM.csv', 'utf8').trim().split(/\r?\n/).slice(1)
  .map(l => l.match(/"([^"]*)"/g).map(x => x.slice(1, -1)));
const lcsc = {};
for (const [, des, , code] of bom) for (const r of des.split(',')) lcsc[r.trim()] = code;

const cpl = fs.readFileSync(DIR + 'fab/jlc/PiDG_Pico_JLC_CPL.csv', 'utf8').trim().split(/\r?\n/);
const header = cpl[0];
const rows = cpl.slice(1).map(l => l.match(/"([^"]*)"/g).map(x => x.slice(1, -1)));

// curl, not Node fetch: the CDN blocks Node's client
function curlJson(url) {
  const raw = execFileSync('curl', ['-s', '-m', '30', url, '-H',
    'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'],
    { maxBuffer: 64 << 20 }).toString();
  return JSON.parse(raw);
}

// EasyEDA Pro: product search -> footprint uuid -> footprint document (cached in ./eda)
function eda(code) {
  const f = path.join(S, 'eda', code + '.json');
  if (fs.existsSync(f)) return JSON.parse(fs.readFileSync(f, 'utf8'));
  fs.mkdirSync(path.join(S, 'eda'), { recursive: true });
  const sr = curlJson('https://pro.easyeda.com/api/eda/product/search?keyword=' + code);
  const prod = ((sr.result && sr.result.productList) || []).find(p => p.number === code);
  const fpu = prod && prod.device_info && prod.device_info.attributes.Footprint;
  const j = fpu ? { code, fp: curlJson('https://pro.easyeda.com/api/v2/components/' + fpu).result } : { code, fp: null };
  fs.writeFileSync(f, JSON.stringify(j));
  return j;
}

// Newer LCSC footprints keep dataStr in an AES-256-GCM blob (key/iv in the record, 16-byte tag at the end, gzip inside).
function dataStr(fp) {
  if (fp.dataStr) return fp.dataStr;
  if (!fp.dataStrId || !fp.key || !fp.iv) return null;
  const f = path.join(S, 'eda', fp.uuid + '.blob');
  if (!fs.existsSync(f)) execFileSync('curl', ['-s', '-m', '30', '-o', f, fp.dataStrId, '-H', 'User-Agent: Mozilla/5.0']);
  const b = fs.readFileSync(f), c = require('crypto');
  const d = c.createDecipheriv('aes-256-gcm', Buffer.from(fp.key, 'hex'), Buffer.from(fp.iv, 'hex'));
  d.setAuthTag(b.subarray(b.length - 16));
  return require('zlib').gunzipSync(Buffer.concat([d.update(b.subarray(0, b.length - 16)), d.final()])).toString();
}

// EasyEDA Pro pads (mil, y up, origin = part centre) -> mm, y down
function edaPads(j) {
  const ds = j && j.fp && dataStr(j.fp);
  if (!ds) return null;
  const L = ds.split(/\r?\n/).filter(Boolean).map(l => JSON.parse(l));
  const pads = L.filter(l => l[0] === 'PAD').map(l => ({ n: String(l[5]), x: l[6] * 0.0254, y: -l[7] * 0.0254 }));
  const name = (L.find(l => l[0] === 'ATTR' && l[7] === 'Footprint') || [])[8] || '?';
  return { title: name, pads };
}

const rot = (p, deg) => { // counter-clockwise on screen, y-down frame
  const a = deg * Math.PI / 180, c = Math.round(Math.cos(a) * 1e9) / 1e9, s = Math.round(Math.sin(a) * 1e9) / 1e9;
  return { ...p, x: p.x * c + p.y * s, y: -p.x * s + p.y * c };
};

function fit(kpads, epads) {
  const out = [];
  for (const R of [0, 90, 180, 270]) {
    const e = epads.map(p => rot(p, R));
    const uniq = n => kpads.filter(p => p.n === n).length === 1 && e.filter(p => p.n === n).length === 1;
    const common = [...new Set(kpads.map(p => p.n))].filter(n => n && uniq(n));
    let tx, ty;
    if (common.length) {
      tx = common.reduce((a, n) => a + kpads.find(p => p.n === n).x - e.find(p => p.n === n).x, 0) / common.length;
      ty = common.reduce((a, n) => a + kpads.find(p => p.n === n).y - e.find(p => p.n === n).y, 0) / common.length;
    } else {
      const m = a => a.reduce((s, v) => s + v, 0) / a.length;
      tx = m(kpads.map(p => p.x)) - m(e.map(p => p.x)); ty = m(kpads.map(p => p.y)) - m(e.map(p => p.y));
    }
    let worst = 0;
    for (const k of kpads) {
      const same = e.filter(p => p.n === k.n), pool = same.length ? same : e;
      worst = Math.max(worst, Math.min(...pool.map(p => Math.hypot(k.x - (p.x + tx), k.y - (p.y + ty)))));
    }
    out.push({ R, tx, ty, worst, common: common.length });
  }
  out.sort((a, b) => a.worst - b.worst || a.R - b.R);
  if (out[0].worst <= 0.3) return out;
  const k1 = kpads.find(p => p.n === '1'), e1 = epads.find(p => p.n === '1');
  if (!k1 || !e1) return out;
  const geo = [0, 90, 180, 270].map(R => {
    const e = epads.map(p => rot(p, R)), r1 = rot(e1, R), tx = k1.x - r1.x, ty = k1.y - r1.y;
    const worst = Math.max(...kpads.map(k => Math.min(...e.map(p => Math.hypot(k.x - (p.x + tx), k.y - (p.y + ty))))));
    return { R, tx, ty, worst, geometric: true };
  }).sort((a, b) => a.worst - b.worst || a.R - b.R);
  return geo[0].worst < out[0].worst ? geo : out;
}

const lines = [header], rep = [], cache = {};
for (const [ref, mx, my, layer, r0] of rows) {
  const k = kp[ref], code = lcsc[ref];
  const keep = why => { lines.push(`"${ref}","${mx}","${my}","${layer}","${r0}"`); rep.push(`${ref.padEnd(4)} ${String(code).padEnd(10)} UNCHANGED: ${why}`); };
  if (!k || !code) { keep('no LCSC number or footprint'); continue; }
  if (!(code in cache)) cache[code] = edaPads(eda(code));
  const e = cache[code];
  if ((!e || !e.pads.length) && /^(R|C)_[0-9]{4}_/.test(k.fp) && k.pads.length === 2) {
    lines.push(`"${ref}","${k.x.toFixed(4)}","${(-k.y).toFixed(4)}","${layer}","${+k.rot.toFixed(2)}"`);
    rep.push(`${ref.padEnd(4)} ${code.padEnd(10)} ${k.fp.slice(0, 36).padEnd(36)} no JLC footprint; chip passive, corr 0 | rot ${r0} -> ${+k.rot.toFixed(2)}`);
    continue;
  }
  if (!e || !e.pads.length) { keep('no JLC footprint found'); continue; }
  const res = fit(k.pads.filter(p => p.n !== ''), e.pads), best = res[0];
  const alt = res.filter(r => r.R !== best.R && r.worst - best.worst < 0.05).map(r => r.R);
  const off = rot({ x: best.tx, y: best.ty }, k.rot);
  const X = k.x + off.x, Y = k.y + off.y, ROT = (k.rot + best.R) % 360;
  lines.push(`"${ref}","${X.toFixed(4)}","${(-Y).toFixed(4)}","${layer}","${+ROT.toFixed(2)}"`);
  rep.push(`${ref.padEnd(4)} ${code.padEnd(10)} ${k.fp.slice(0, 36).padEnd(36)} JLC "${e.title.slice(0, 34)}" | corr ${String(best.R).padStart(3)} | rot ${r0} -> ${+ROT.toFixed(2)} | shift ${Math.hypot(off.x, off.y).toFixed(3)} mm | fit ${best.worst.toFixed(3)} mm` +
    (alt.length ? ` | symmetric, also fits ${alt.join('/')}` : '') + (best.geometric ? ' | matched by geometry (pad numbers differ)' : '') + (best.worst > 0.2 ? '  << CHECK' : ''));
}
fs.writeFileSync(path.join(S, 'cpl_new.csv'), lines.join('\r\n') + '\r\n');
fs.writeFileSync(path.join(S, 'rot_report.txt'), rep.join('\n') + '\n');
console.log(rep.join('\n'));
