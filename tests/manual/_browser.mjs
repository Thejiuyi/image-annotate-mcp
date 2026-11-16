// Shared plumbing for the manual browser checks: find puppeteer-core, find a browser.
//
// Neither is hard-coded to one machine:
//   PUPPETEER_ROOT  a directory that has node_modules (defaults to normal resolution)
//   BROWSER_BIN     path to msedge / chrome (defaults to the usual install spots)

import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';
import { platform } from 'node:process';

const BROWSERS = {
  win32: [
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  ],
  darwin: [
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ],
  linux: ['/usr/bin/microsoft-edge', '/usr/bin/google-chrome', '/usr/bin/chromium'],
};

export function puppeteerCore() {
  const roots = [];
  if (process.env.PUPPETEER_ROOT) {
    roots.push(`${process.env.PUPPETEER_ROOT.replace(/[\\/]+$/, '')}/package.json`);
  }
  roots.push(import.meta.url);
  for (const root of roots) {
    try {
      return createRequire(root)('puppeteer-core');
    } catch (err) {
      if (err.code !== 'MODULE_NOT_FOUND') throw err;
    }
  }
  throw new Error(
    '找不到 puppeteer-core。装一下：npm i -D puppeteer-core，' +
      '或用 PUPPETEER_ROOT 指向已装好它的目录。'
  );
}

export function browserPath() {
  const forced = process.env.BROWSER_BIN;
  if (forced) {
    if (!existsSync(forced)) throw new Error(`BROWSER_BIN 指向的文件不存在：${forced}`);
    return forced;
  }
  for (const candidate of BROWSERS[platform] || []) {
    if (existsSync(candidate)) return candidate;
  }
  throw new Error('找不到 Edge / Chrome。装一个，或用 BROWSER_BIN 指到浏览器可执行文件。');
}
