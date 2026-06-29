#!/usr/bin/env node
// Usage: node scripts/screenshot.js [url] [output.png]
// Defaults: http://localhost:5173  screenshots/app-<timestamp>.png
const { chromium } = require('../frontend/node_modules/playwright');
const path = require('path');
const fs = require('fs');

const url = process.argv[2] || 'http://localhost:5173';
const outDir = path.join(__dirname, '..', 'screenshots');
fs.mkdirSync(outDir, { recursive: true });
const defaultOut = path.join(outDir, `app-${Date.now()}.png`);
const outFile = process.argv[3] || defaultOut;

(async () => {
  const browser = await chromium.launch({
    executablePath: '/home/etienne/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome',
  });
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(url, { waitUntil: 'networkidle', timeout: 15000 });
  await page.screenshot({ path: outFile, fullPage: false });
  await browser.close();
  console.log(outFile);
})();
