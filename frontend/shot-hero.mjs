import { chromium } from "@playwright/test";
const out = process.argv[2];
const browser = await chromium.launch();
for (const [width, height] of [[1440, 1000], [390, 844]]) {
  const page = await browser.newPage({ viewport: { width, height } });
  const logs = [];
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) logs.push(`${m.type()}: ${m.text().slice(0, 200)}`); });
  page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
  await page.goto("http://localhost:3000/", { waitUntil: "networkidle" });
  await page.waitForTimeout(2200); // let the staggered entrance animations finish
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
  await page.screenshot({ path: `${out}/hero-${width}.png` });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  const img = await page.locator('img[alt^="CloudPulse overview"]').evaluate((el) => ({ w: el.clientWidth, natural: el.naturalWidth, src: el.currentSrc.slice(-60) }));
  const htmlClass = await page.evaluate(() => document.documentElement.className);
  console.log(`${width}: overflowX=${overflow} img=${JSON.stringify(img)} htmlClass="${htmlClass}"`);
  for (const l of logs) console.log("   ", l);
}
await browser.close();
