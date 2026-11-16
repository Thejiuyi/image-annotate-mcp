// Capture a frame sequence for docs/demo.gif.
//
//   node tests/manual/make_gif.mjs "http://127.0.0.1:8990/?s=s1"
//
// Writes out/gif/frame-*.png; tests/manual/make_gif.py assembles them.

import { browserPath, puppeteerCore } from './_browser.mjs';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const puppeteer = puppeteerCore();

const EDGE = browserPath();
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, 'out', 'gif');
const url = process.argv[2];
if (!url) {
  console.error('用法: node make_gif.mjs <url>');
  process.exit(2);
}

// 视口现在是一个固定高度的画布区，整屏都值得拍
const CLIP = { x: 0, y: 0, width: 1280, height: 780 };
// Diamond around the card, in image pixels. Four straight segments, no curves.
const POLY = [[505, 175], [745, 340], [505, 505], [265, 340]];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let index = 0;

async function shot(page) {
  const name = `frame-${String(index++).padStart(2, '0')}.png`;
  await page.screenshot({ path: resolve(OUT, name), clip: CLIP });
}

async function main() {
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: true,
    args: ['--no-proxy-server', '--disable-gpu', '--hide-scrollbars'],
    defaultViewport: { width: 1280, height: 780, deviceScaleFactor: 2 },
  });
  const page = await browser.newPage();
  page.on('dialog', (d) => d.accept());
  await page.goto(url, { waitUntil: 'networkidle0', timeout: 20000 });
  await page.waitForFunction(() => document.getElementById('img').naturalWidth > 0, {
    timeout: 15000,
  });
  await sleep(400);
  await shot(page); // empty state

  const geo = await page.evaluate(() => {
    const r = document.getElementById('img').getBoundingClientRect();
    const img = document.getElementById('img');
    return { x: r.x, y: r.y, w: r.width, nw: img.naturalWidth };
  });
  const scale = geo.nw / geo.w;
  const toClient = (ix, iy) => [geo.x + ix / scale, geo.y + iy / scale];

  const box = [982, 163, 176, 174];
  const [x0, y0] = toClient(box[0], box[1]);
  const [x1, y1] = toClient(box[0] + box[2], box[1] + box[3]);
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  await page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, { steps: 8 });
  await sleep(120);
  await shot(page); // mid-drag
  await page.mouse.move(x1, y1, { steps: 8 });
  await page.mouse.up();
  await sleep(120);
  await shot(page); // first box

  const box2 = [1042, 512, 216, 96];
  const [a0, b0] = toClient(box2[0], box2[1]);
  const [a1, b1] = toClient(box2[0] + box2[2], box2[1] + box2[3]);
  await page.mouse.move(a0, b0);
  await page.mouse.down();
  await page.mouse.move(a1, b1, { steps: 10 });
  await page.mouse.up();
  await sleep(120);
  await shot(page); // second box

  await page.click('#mPt');
  const [px, py] = toClient(131, 559);
  await page.mouse.click(px, py);
  await sleep(120);
  await shot(page); // point placed

  // polygon: three clicks, then hover the fourth vertex so the rubber band shows
  await page.click('#mPoly');
  for (const [vx, vy] of POLY.slice(0, 3)) {
    const [cx, cy] = toClient(vx, vy);
    await page.mouse.click(cx, cy);
    await sleep(90);
  }
  const [hx, hy] = toClient(POLY[3][0], POLY[3][1]);
  await page.mouse.move(hx, hy, { steps: 10 });
  await sleep(150);
  await shot(page); // three vertices + rubber band
  await page.mouse.click(hx, hy);
  await sleep(100);
  await page.keyboard.press('Enter');
  await sleep(150);
  await shot(page); // closed
  await page.click('#mBox');

  // 滚轮缩放：以光标为中心放大，线宽和字号在屏幕上保持原大小
  const [zx, zy] = toClient(640, 330);
  await page.mouse.move(zx, zy, { steps: 8 });
  for (let i = 0; i < 5; i++) {
    await page.mouse.wheel({ deltaY: -100 });
    await sleep(120);
  }
  await sleep(250);
  await shot(page); // zoomed in
  await page.click('#zoomFit');
  await sleep(250);

  // 放大镜：光标停在红色按钮的圆角上，5 倍下能看清抗锯齿
  await page.click('#loupeToggle');
  await sleep(200);
  const [mx, my] = toClient(1046, 516);
  await page.mouse.move(mx, my, { steps: 10 });
  await sleep(300);
  await shot(page); // loupe
  await page.click('#loupeToggle');
  await sleep(200);

  const names = ['crystal', 'attack', 'shop', 'skill_ring'];
  const inputs = await page.$$('#list input');
  for (let i = 0; i < inputs.length; i++) {
    await inputs[i].click();
    await page.keyboard.down('Control');
    await page.keyboard.press('KeyA');
    await page.keyboard.up('Control');
    await page.keyboard.type(names[i]);
  }
  await page.mouse.click(geo.x + 10, geo.y + 620);
  await sleep(150);
  await shot(page); // renamed

  await page.click('#save');
  await page.waitForFunction(
    () => document.getElementById('statePill').textContent.includes('已保存'),
    { timeout: 15000 }
  );
  await sleep(500);
  await shot(page); // saved

  console.log(`frames: ${index}`);
  await browser.close();
}

main().catch((e) => {
  console.error('FAILED', e);
  process.exit(1);
});
