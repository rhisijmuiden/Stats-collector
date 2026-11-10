// Regenerates the manual screenshots (docs/manual/images/{en,nl}-*.png) from a running Stats Collector.
// Usage (from frontend/): node scripts/screenshots.mjs <base-url> <setup-link>
import { chromium } from "playwright";

const [base = "http://127.0.0.1:8080", setupLink] = process.argv.slice(2);
const out = new URL("../../docs/manual/images/", import.meta.url).pathname;
const SCREENS = [
  ["/", "dashboard"], ["/content", "content"], ["/content", "content-item", "table .link-btn"], ["/editors", "editors"],
  ["/admin/sources", "sources"], ["/admin/sources", "sources-youtube", 'tr:has-text("Demo YouTube") button:has(svg.lucide-pencil)'], ["/admin/sso", "sso"],
  ["/info", "info"], ["/admin/backup", "backup"], ["/admin/email", "email"], ["/admin/branding", "branding"],
];

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const ctx = await browser.newContext({ viewport: { width: 1280, height: 820 }, deviceScaleFactor: 2, timezoneId: "Europe/Amsterdam", locale: "en-GB" });
const page = await ctx.newPage();
const password = "screenshot-password-123";

if (setupLink) {
  await page.goto(setupLink);
  const inputs = page.locator("form input");
  await inputs.nth(0).fill("Alex Admin");
  await inputs.nth(1).fill("admin@example.org");
  await inputs.nth(2).fill(password);
  await inputs.nth(3).fill(password);
  await page.locator("form button.btn").click();
} else {
  await page.goto(`${base}/login`);
  await page.fill("input[type=email]", "admin@example.org");
  await page.fill("input[type=password]", password);
  await page.locator("form button.btn").first().click();
}
await page.waitForURL(`${base}/`);

for (const lang of ["en", "nl"]) {
  await page.evaluate(async (language) => {
    const me = await (await fetch("/api/auth/me")).json();
    await fetch("/api/auth/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token },
      body: JSON.stringify({ language, theme: "light" }),
    });
  }, lang);
  for (const [path, name, click] of SCREENS) {
    await page.goto(base + path);
    await page.waitForLoadState("networkidle");
    if (click) {
      await page.locator(click).first().click();
      await page.waitForLoadState("networkidle");
    }
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${out}${lang}-${name}.png` });
    console.log(`${lang}-${name}.png`);
  }
}
await browser.close();
