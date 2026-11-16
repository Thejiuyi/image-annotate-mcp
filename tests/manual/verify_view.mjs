// Manual verification for wheel zoom, pan and the loupe.
//
//   node tests/manual/verify_view.mjs "http://127.0.0.1:8992/?s=s1"
//
// The interesting assertions are all "the same image pixel under the same screen
// pixel": zoom must not shift the mapping, pan must not shift it either, and the
// loupe must show the pixel the cursor is on. Screenshots go to out/ for a human
// to look at, because assertions cannot see a broken layout.

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
  console.error('用法: node verify_view.mjs <url>');
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const checks = [];
const check = (label, ok, detail = '') => checks.push({ label, ok: !!ok, detail: String(detail) });

// <img> 的视觉矩形就是「图像现在的样子」，zoom/pan 全在里面
async function readGeo(page) {
  return page.evaluate(() => {
    const img = document.getElementById('img');
    const st = document.getElementById('stage');
    const ir = img.getBoundingClientRect();
    const sr = st.getBoundingClientRect();
    return {
      img: { x: ir.x, y: ir.y, w: ir.width, h: ir.height },
      stage: { x: sr.x, y: sr.y, w: sr.width, h: sr.height },
      nw: img.naturalWidth, nh: img.naturalHeight,
      dpr: window.devicePixelRatio,
    };
  });
}

const toClient = (geo, ix, iy) => [
  geo.img.x + (ix * geo.img.w) / geo.nw,
  geo.img.y + (iy * geo.img.h) / geo.nh,
];

const zoomPct = (page) =>
  page.$eval('#zoomFit', (el) => parseInt(el.textContent, 10));

const cursorText = (page) => page.$eval('#cursor', (el) => el.textContent.trim());

async function readCursor(page, cx, cy) {
  await page.mouse.move(cx, cy, { steps: 4 });
  await sleep(90);
  return cursorText(page);
}

const parseCursor = (t) => {
  const m = /\((-?\d+),\s*(-?\d+)\)/.exec(t || '');
  return m ? [Number(m[1]), Number(m[2])] : null;
};

const stageCenter = (geo) => [geo.stage.x + geo.stage.w / 2, geo.stage.y + geo.stage.h / 2];

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
  await sleep(300);
  const geo0 = await readGeo(page);

  // ---- 默认状态 -----------------------------------------------------------
  const loupeHidden0 = await page.$eval('#loupe', (el) => el.hidden);
  const wheelOn0 = await page.$eval('#wheelToggle', (el) => el.classList.contains('on'));
  const sizeDisabled0 = await page.$eval('#loupeSize', (el) => el.disabled);
  check('放大镜默认关', loupeHidden0 === true, String(loupeHidden0));
  check('滚轮缩放默认开', wheelOn0 === true, String(wheelOn0));
  check('放大镜关着时尺寸不可调', sizeDisabled0 === true);
  check('初始缩放显示 100%', (await zoomPct(page)) === 100);

  // ---- 滚轮缩放：锚点下的图像像素不能动 -----------------------------------
  const [ax, ay] = [geo0.stage.x + geo0.stage.w * 0.45, geo0.stage.y + geo0.stage.h * 0.45];
  const before = parseCursor(await readCursor(page, ax, ay));
  await page.mouse.wheel({ deltaY: -100 });
  await sleep(120);
  await page.mouse.wheel({ deltaY: -100 });
  await sleep(120);
  await page.mouse.wheel({ deltaY: -100 });
  await sleep(200);
  const after = parseCursor(await readCursor(page, ax, ay));
  const pct1 = await zoomPct(page);
  const geo1 = await readGeo(page);

  check('滚轮之后确实放大了', pct1 > 100, `${pct1}%`);
  check(
    '放大后锚点下的图像像素不变',
    before && after && Math.abs(before[0] - after[0]) <= 1 && Math.abs(before[1] - after[1]) <= 1,
    `${before} -> ${after}`
  );
  check(
    '图像视觉宽度按比例变大',
    Math.abs(geo1.img.w / geo0.img.w - pct1 / 100) < 0.02,
    `${(geo1.img.w / geo0.img.w).toFixed(3)} vs ${(pct1 / 100).toFixed(3)}`
  );
  await page.screenshot({ path: resolve(OUT, 'view-zoomed.png') });

  // ---- 关掉滚轮就不该再变 -------------------------------------------------
  await page.click('#wheelToggle');
  await sleep(120);
  await page.mouse.wheel({ deltaY: -100 });
  await sleep(200);
  const pctOff = await zoomPct(page);
  check('关掉滚轮缩放后滚轮无效', pctOff === pct1, `${pct1}% -> ${pctOff}%`);
  await page.click('#wheelToggle');
  await sleep(120);

  // ---- 放大状态下点击仍然精确 ---------------------------------------------
  const [cxp, cyp] = stageCenter(geo1);
  const aimedPoint = parseCursor(await readCursor(page, cxp, cyp));
  await page.click('#mPt');
  await page.mouse.click(cxp, cyp);
  await sleep(120);
  await page.click('#mBox');
  await sleep(120);

  // 放大状态下拖一个框，两端的图像坐标都要对得上
  const [bx0, by0] = [geo1.stage.x + geo1.stage.w * 0.18, geo1.stage.y + geo1.stage.h * 0.2];
  const [bx1, by1] = [bx0 + 130, by0 + 90];
  const aim0 = parseCursor(await readCursor(page, bx0, by0));
  const aim1 = parseCursor(await readCursor(page, bx1, by1));
  await page.mouse.move(bx0, by0);
  await page.mouse.down();
  await page.mouse.move((bx0 + bx1) / 2, (by0 + by1) / 2, { steps: 6 });
  await page.mouse.move(bx1, by1, { steps: 6 });
  await page.mouse.up();
  await sleep(150);

  // ---- 中键拖动平移 -------------------------------------------------------
  const beforePan = (await readGeo(page)).img;
  await page.mouse.move(cxp, cyp);
  await page.mouse.down({ button: 'middle' });
  await page.mouse.move(cxp + 70, cyp + 50, { steps: 8 });
  await page.mouse.up({ button: 'middle' });
  await sleep(200);
  const afterPan = (await readGeo(page)).img;
  check(
    '中键拖动平移了图像',
    Math.abs(afterPan.x - beforePan.x - 70) <= 2 && Math.abs(afterPan.y - beforePan.y - 50) <= 2,
    `dx=${(afterPan.x - beforePan.x).toFixed(1)} dy=${(afterPan.y - beforePan.y).toFixed(1)}`
  );

  // 平移之后同一个屏幕点还是同一个图像像素
  const [px2, py2] = stageCenter(await readGeo(page));
  const aimedAfterPan = parseCursor(await readCursor(page, px2, py2));
  await page.click('#mPt');
  await page.mouse.click(px2, py2);
  await sleep(120);
  await page.click('#mBox');
  await sleep(120);

  // ---- 复位 ---------------------------------------------------------------
  await page.click('#zoomFit');
  await sleep(200);
  const geoReset = await readGeo(page);
  check('复位回到 100%', (await zoomPct(page)) === 100);
  check(
    '复位后图像宽度回到适应窗口',
    Math.abs(geoReset.img.w - geo0.img.w) < 1,
    `${geoReset.img.w.toFixed(1)} vs ${geo0.img.w.toFixed(1)}`
  );

  // ---- 放大镜 -------------------------------------------------------------
  await page.click('#loupeToggle');
  await sleep(250);
  const loupeShown = await page.$eval('#loupe', (el) => !el.hidden);
  check('点开之后放大镜可见', loupeShown === true);

  // 指针停在纯色块中间，窗口中心那个像素必须等于原图那一个像素
  const geoL = await readGeo(page);
  const [lx, ly] = toClient(geoL, 980, 250);
  await page.mouse.move(lx, ly, { steps: 6 });
  await sleep(250);
  const probe = await page.evaluate(
    ([ix, iy]) => {
      const img = document.getElementById('img');
      const c = document.createElement('canvas');
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      const g = c.getContext('2d');
      g.drawImage(img, 0, 0);
      const src = [...g.getImageData(ix, iy, 1, 1).data];

      const lc = document.getElementById('loupeCv');
      const lg = lc.getContext('2d');
      const cssW = parseFloat(getComputedStyle(lc).width);
      const dpr = lc.width / cssW;
      const N = parseInt(document.getElementById('loupeSize').value, 10);
      const k = cssW / N; // 每个图像像素在窗口里的 CSS 尺寸
      // 光标像素 + 左右各一个，而且贴着色块边缘取：只看纯色中心的话，取样区
      // 整体偏十几个像素颜色也不变（第一版就栽在这儿）；压在 1px 的硬边上，
      // 偏左偏右都会露馅
      const y = Math.round((cssW / 2 + k / 2) * dpr);
      const at = (o) =>
        [...lg.getImageData(Math.round((cssW / 2 + (o + 0.5) * k) * dpr), y, 1, 1).data];
      const got = [-1, 0, 1].map(at);
      const near = [-1, 0, 1].map((o) => [...g.getImageData(ix + o, iy, 1, 1).data]);
      return { src, near, got, k, dpr, info: document.getElementById('loupeInfo').textContent };
    },
    [980, 250]
  );
  const same = probe.got.every((g, i) =>
    probe.near[i].slice(0, 3).every((v, j) => Math.abs(v - g[j]) <= 8)
  );
  check(
    '放大镜中心三格 = 光标处原图三格',
    same,
    `near=${JSON.stringify(probe.near)} got=${JSON.stringify(probe.got)}`
  );
  check('放大镜信息行写着倍数', /80×80 · 2\.5× · \(980, 250\)/.test(probe.info), probe.info);
  await page.screenshot({ path: resolve(OUT, 'view-loupe.png') });

  // ---- 取样范围可调 -------------------------------------------------------
  await page.select('#loupeSize', '120');
  await sleep(200);
  const info120 = await page.$eval('#loupeInfo', (el) => el.textContent);
  check('改成 120×120 后倍数变小', /120×120 · 1\.7×/.test(info120), info120);

  // ---- 窗口可移动，移动后不再跟随 -----------------------------------------
  const headBox = await page.evaluate(() => {
    const r = document.querySelector('#loupe .lh').getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  const pos0 = await page.evaluate(() => {
    const el = document.getElementById('loupe');
    return { l: parseFloat(el.style.left), t: parseFloat(el.style.top) };
  });
  await page.mouse.move(headBox.x, headBox.y);
  await page.mouse.down();
  await page.mouse.move(headBox.x - 120, headBox.y - 90, { steps: 8 });
  await page.mouse.up();
  await sleep(200);
  const pos1 = await page.evaluate(() => {
    const el = document.getElementById('loupe');
    return { l: parseFloat(el.style.left), t: parseFloat(el.style.top) };
  });
  const pinText = await page.$eval('#loupePin', (el) => el.textContent.trim());
  check(
    '拖标题栏把窗口挪走了',
    Math.abs(pos1.l - pos0.l + 120) <= 3 && Math.abs(pos1.t - pos0.t + 90) <= 3,
    `${JSON.stringify(pos0)} -> ${JSON.stringify(pos1)}`
  );
  check('拖动之后变成「已固定」', pinText === '已固定', pinText);

  await page.mouse.move(lx + 200, ly + 120, { steps: 8 });
  await sleep(250);
  const pos2 = await page.evaluate(() => {
    const el = document.getElementById('loupe');
    return { l: parseFloat(el.style.left), t: parseFloat(el.style.top) };
  });
  check(
    '固定之后指针移动不再带动窗口',
    Math.abs(pos2.l - pos1.l) < 1 && Math.abs(pos2.t - pos1.t) < 1,
    `${JSON.stringify(pos1)} -> ${JSON.stringify(pos2)}`
  );
  await page.screenshot({ path: resolve(OUT, 'view-loupe-moved.png') });

  // 点回「已固定」= 恢复跟随
  await page.click('#loupePin');
  await sleep(120);
  const pinBack = await page.$eval('#loupePin', (el) => el.textContent.trim());
  check('再点一下回到「跟随中」', pinBack === '跟随中', pinBack);

  // ---- 保存 ---------------------------------------------------------------
  await page.click('#save');
  await page.waitForFunction(
    () => document.getElementById('statePill').textContent.includes('已保存'),
    { timeout: 15000 }
  );
  await sleep(400);

  const report = {
    ok: problems.length === 0 && checks.every((c) => c.ok),
    problems,
    checks,
    geo0,
    geo1,
    zoomPct: [100, pct1, pctOff],
    aimed: { point: aimedPoint, pointAfterPan: aimedAfterPan, box: [aim0, aim1] },
    loupe: probe,
    state: await page.$eval('#statePill', (el) => el.textContent.trim()),
  };
  writeFileSync(resolve(OUT, 'view-report.json'), JSON.stringify(report, null, 1), 'utf-8');
  console.log(JSON.stringify(report, null, 1));

  await browser.close();
  process.exit(report.ok ? 0 : 1);
}

main().catch((e) => {
  console.error('FAILED', e);
  process.exit(1);
});
