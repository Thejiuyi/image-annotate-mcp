// Manual verification for the polygon tool and the two hidden-layer switches.
//
//   node tests/manual/verify_polygon.mjs "http://127.0.0.1:8991/?s=s1"
//
// Drives Edge with a real mouse: 4 clicks build a polygon, Enter closes it, then a
// box, then the box's eye button hides it, then the global layer toggle is flipped
// twice. Saves, screenshots both hide states, and writes out/polygon-report.json
// with the coordinates it aimed at so the python half can diff them.

import { browserPath, puppeteerCore } from './_browser.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const puppeteer = puppeteerCore();

const EDGE = browserPath();
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, 'out');

const url = process.argv[2];
if (!url) {
  console.error('用法: node verify_polygon.mjs <url>');
  process.exit(2);
}

// Deliberately awkward numbers, in the image's own pixel space.
const POLY = [[300, 200], [620, 240], [560, 520], [250, 460]];
const BOX = [820, 380, 200, 120];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function readGeo(page) {
  return page.evaluate(() => {
    const cv = document.getElementById('cv');
    const img = document.getElementById('img');
    const r = img.getBoundingClientRect();
    return {
      x: r.x, y: r.y, w: r.width, h: r.height,
      nw: img.naturalWidth, nh: img.naturalHeight,
      dpr: window.devicePixelRatio,
    };
  });
}

const toClient = (geo, ix, iy) => {
  const scale = geo.nw / geo.w;
  return [geo.x + ix / scale, geo.y + iy / scale];
};

async function clickAt(page, geo, ix, iy) {
  const [cx, cy] = toClient(geo, ix, iy);
  await page.mouse.click(cx, cy);
  await sleep(60);
}

async function drawBox(page, geo, box) {
  const [x0, y0] = toClient(geo, box[0], box[1]);
  const [x1, y1] = toClient(geo, box[0] + box[2], box[1] + box[3]);
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  await page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, { steps: 6 });
  await page.mouse.move(x1, y1, { steps: 6 });
  await page.mouse.up();
  await sleep(80);
}

const listState = (page) =>
  page.evaluate(() =>
    [...document.querySelectorAll('#list .item')].map((el) => ({
      name: el.querySelector('input')?.value ?? '',
      off: el.classList.contains('off'),
      eye: el.querySelector('.eye')?.textContent?.trim() ?? '',
      coord: el.querySelector('.coord')?.textContent?.trim() ?? '',
    }))
  );

async function main() {
  mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: true,
    args: ['--no-proxy-server', '--disable-gpu', '--hide-scrollbars'],
    defaultViewport: { width: 1440, height: 920, deviceScaleFactor: 2 },
  });
  const page = await browser.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push('pageerror: ' + e.message));
  page.on('console', (m) => {
    if (m.type() === 'error') problems.push('console: ' + m.text());
  });
  page.on('dialog', (d) => d.accept());

  await page.goto(url, { waitUntil: 'networkidle0', timeout: 20000 });
  await page.waitForFunction(() => document.getElementById('img').naturalWidth > 0, {
    timeout: 15000,
  });
  await sleep(250);
  const geo = await readGeo(page);

  // 1) polygon: click every vertex, then Enter
  await page.click('#mPoly');
  for (const [vx, vy] of POLY) await clickAt(page, geo, vx, vy);
  await page.keyboard.press('Enter');
  await sleep(150);
  const afterPoly = await listState(page);

  // 2) box, drawn after switching back to box mode
  await page.click('#mBox');
  await drawBox(page, geo, BOX);
  const afterBox = await listState(page);

  // 3) per-item eye button on the box (second row)
  const eyes = await page.$$('#list .eye');
  if (eyes.length < 2) throw new Error(`expected 2 eye buttons, got ${eyes.length}`);
  await eyes[1].click();
  await sleep(150);
  const afterEye = await listState(page);
  await page.screenshot({ path: resolve(OUT, 'polygon-item-hidden.png') });

  // 4) global layer toggle: on, screenshot, back off
  await page.click('#hide');
  await sleep(200);
  const hideLabelOn = await page.$eval('#hide', (el) => el.textContent.trim());
  const canvasHidden = await page.$eval('#cv', (el) => el.classList.contains('hidden-layer'));
  await page.screenshot({ path: resolve(OUT, 'polygon-all-hidden.png') });
  await page.click('#hide');
  await sleep(200);
  const hideLabelOff = await page.$eval('#hide', (el) => el.textContent.trim());

  await page.screenshot({ path: resolve(OUT, 'polygon-before-save.png') });
  await page.click('#save');
  await page.waitForFunction(
    () => document.getElementById('statePill').textContent.includes('已保存'),
    { timeout: 15000 }
  );
  await sleep(400);

  const report = {
    ok: problems.length === 0,
    problems,
    geo,
    aimed: { polygon: POLY, box: BOX },
    afterPoly,
    afterBox,
    afterEye,
    hideLabelOn,
    hideLabelOff,
    canvasHidden,
    state: await page.$eval('#statePill', (el) => el.textContent.trim()),
  };
  writeFileSync(resolve(OUT, 'polygon-report.json'), JSON.stringify(report, null, 1), 'utf-8');
  console.log(JSON.stringify(report, null, 1));

  await browser.close();
  process.exit(problems.length ? 1 : 0);
}

main().catch((e) => {
  console.error('FAILED', e);
  process.exit(1);
});
