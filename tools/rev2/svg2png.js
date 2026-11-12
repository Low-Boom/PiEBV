// SVG -> PNG with a headless Chromium (Playwright). usage: node svg2png.js IN.svg OUT.png [WIDTH_PX] [BACKGROUND]
const { chromium } = require('playwright');
(async () => {
  const [, , src, dst, width = '2000', bg = '#ffffff'] = process.argv;
  let svg = require('fs').readFileSync(src, 'utf8');
  const [, , vw, vh] = svg.match(/viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"/).slice(1).map(Number);
  const w = +width, h = Math.round(w * vh / vw);
  svg = svg.replace(/<svg[^>]*>/, m => m.replace(/\swidth="[^"]*"/, ` width="${w}"`).replace(/\sheight="[^"]*"/, ` height="${h}"`));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  await page.setContent(`<body style="margin:0;background:${bg}">${svg}</body>`);
  await page.screenshot({ path: dst });
  await browser.close();
})();
