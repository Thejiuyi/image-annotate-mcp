// Manual verification: drive the annotation page with a real browser and a real mouse.
//
//   node tests/manual/verify_page.mjs "http://127.0.0.1:8990/?s=s1"
//
// Draws boxes/points at known *image* coordinates on every image tab, renames
// them, saves, screenshots the page, and writes out/browser-report.json with the
// coordinates it aimed at so the python half can be compared against them.

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
  console.error('用法: node verify_page.mjs <url>');
  process.exit(2);
}

// Per-image targets, in that image's own pixel space. Deliberately awkward numbers.
const PLAN = [
  {
    boxes: [
      { name: 'crystal', box: [982, 163, 176, 174] },
      { name: 'attack', box: [1042, 512, 216, 96] },
    ],
    point: { name: 'shop', point: [131, 559] },
  },
  {
    boxes: [{ name: 'card', box: [248, 204, 312, 272] }],
    point: null,
  },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function readGeo(page) {
  // 用 <img> 的视觉矩形：画布现在铺满视口，只有图像那一层知道 zoom/pan
  return page.evaluate(() => {
    const cv = document.getElementById('cv');
    const img = document.getElementById('img');
    const r = img.getBoundingClientRect();
    return {
      x: r.x, y: r.y, w: r.width, h: r.height,
      nw: img.naturalWidth, nh: img.naturalHeight,
      dpr: window.devicePixelRatio,
      canvasBacking: [cv.width, cv.height],
      currentImage: document.querySelector('#tabs button.on')?.textContent || 'img1',
    };
  });
}

async function drawBox(page, geo, box) {
  const scale = geo.nw / geo.w;
  const toClient = (ix, iy) => [geo.x + ix / scale, geo.y + iy / scale];
  const [x0, y0] = toClient(box[0], box[1]);
  const [x1, y1] = toClient(box[0] + box[2], box[1] + box[3]);
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  await page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, { steps: 6 });
  await page.mouse.move(x1, y1, { steps: 6 });
  await page.mouse.up();
  await sleep(70);
}

async function clickPoint(page, geo, point) {
  const scale = geo.nw / geo.w;
  const [px, py] = [geo.x + point[0] / scale, geo.y + point[1] / scale];
  await page.click('#mPt');
  await page.mouse.click(px, py);
  await page.click('#mBox');
  await sleep(70);
}

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

  const tabCount = await page.$$eval('#tabs button', (els) => els.length);
  const perImage = [];

  for (let t = 0; t < Math.max(1, tabCount); t++) {
    if (t > 0) {
      await page.click(`#tabs button:nth-child(${t + 1})`);
      await sleep(400);
      await page.waitForFunction(
        (idx) => {
          const btn = document.querySelectorAll('#tabs button')[idx];
          return btn && btn.classList.contains('on') && document.getElementById('img').naturalWidth > 0;
        },
        { timeout: 10000 },
        t
      );
    }
    const geo = await readGeo(page);
    const plan = PLAN[t] || { boxes: [], point: null };
    const names = [];
    for (const item of plan.boxes) {
      await drawBox(page, geo, item.box);
      names.push(item.name);
    }
    if (plan.point) {
      await clickPoint(page, geo, plan.point.point);
      names.push(plan.point.name);
    }

    // rename just the items of the current image
    // the sidebar only ever shows the current image's items
    const inputs = await page.$$('#list input');
    for (let i = 0; i < inputs.length; i++) {
      await inputs[i].click();
      await page.keyboard.down('Control');
      await page.keyboard.press('KeyA');
      await page.keyboard.up('Control');
      await page.keyboard.type(names[i] || `item${i + 1}`);
    }
    perImage.push({ tab: t, geo, aimed: plan, renamed: names });
    await page.mouse.click(geo.x + 10, geo.y + geo.h + 30);
  }

  await page.screenshot({ path: resolve(OUT, 'page-before-save.png') });
  await page.click('#save');
  await page.waitForFunction(
    () => document.getElementById('statePill').textContent.includes('已保存'),
    { timeout: 15000 }
  );
  await sleep(400);
  await page.screenshot({ path: resolve(OUT, 'page-after-save.png') });

  const state = await page.evaluate(() => ({
    state: document.getElementById('statePill').textContent,
    toast: document.getElementById('toast').textContent,
    tabs: document.querySelectorAll('#tabs button').length,
    session: document.getElementById('sessionPill').textContent,
  }));

  const report = { ok: problems.length === 0, problems, tabCount, perImage, state };
  writeFileSync(resolve(OUT, 'browser-report.json'), JSON.stringify(report, null, 1), 'utf-8');
  console.log(JSON.stringify(report, null, 1));

  await browser.close();
  process.exit(problems.length ? 1 : 0);
}

main().catch((e) => {
  console.error('FAILED', e);
  process.exit(1);
});
