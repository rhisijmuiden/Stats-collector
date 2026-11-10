// Regenerates the manual screenshots (docs/manual/images/{en,nl}-*.png) from a running Stats Collector.
// Usage (from frontend/): node scripts/screenshots.mjs <base-url> <setup-link>
import { chromium } from "playwright";

const [base = "http://127.0.0.1:8080", setupLink] = process.argv.slice(2);
const out = new URL("../../docs/manual/images/", import.meta.url).pathname;
// Steps for screens that need more than one click: an article with linked posts, an editor's social numbers.
async function openLinkedArticle(page) {
  await page.locator(".seg button").nth(3).click(); // 90 days
  await page.locator(".filters select").first().selectOption({ label: "Demo Website" });
  await page.locator(".filters select").last().selectOption("published");
  await page.locator(".filters .search input").fill("brug");
  await page.locator(".filters .search input").press("Enter");
  await page.waitForLoadState("networkidle");
  await page.locator("table .link-btn").first().click();
  await page.waitForLoadState("networkidle");
  await page.locator(".links-box").scrollIntoViewIfNeeded();
}
async function openEditorSocial(page) {
  await page.locator('table .link-btn:has-text("Anne")').first().click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(300);
  await page.locator(".modal .kpis").last().scrollIntoViewIfNeeded();
}

async function editDashboardWidget(page) {
  await page.locator(".dash-bar .btn.secondary").first().click(); // Edit
  await page.locator('.dash-cell.full .dash-tools button:has(svg.lucide-pencil)').first().click();
  await page.waitForTimeout(300);
}

// The wall itself is served by the wall service on port 8081 (the link may show the public address).
async function openLiveWall(page) {
  const link = await page.locator(".copy-field input").first().inputValue();
  await page.goto(link.replace(/^https?:\/\/[^/]+/, process.env.WALL_BASE || "http://127.0.0.1:8081"));
  await page.waitForTimeout(2500);
}

const SCREENS = [
  ["/", "dashboard"], ["/dashboards", "dashboards"], ["/dashboards", "dashboards-edit", editDashboardWidget], ["/content", "content"], ["/content", "content-item", "table .link-btn"], ["/content", "content-links", openLinkedArticle], ["/editors", "editors"], ["/editors", "editor-social", openEditorSocial], ["/followers", "followers"], ["/goals", "goals"], ["/goals", "goal-detail", ".goal-card"],
  ["/admin/sources", "sources"], ["/admin/sources", "sources-youtube", 'tr:has-text("Demo YouTube") button:has(svg.lucide-pencil)'], ["/admin/sources", "sources-facebook", 'tr:has-text("Demo Facebook") button:has(svg.lucide-pencil)'], ["/admin/sources", "sources-threads", 'tr:has-text("Demo Threads") button:has(svg.lucide-pencil)'], ["/admin/sources", "sources-x", 'tr:has-text("Demo X") button:has(svg.lucide-pencil)'], ["/admin/sources", "sources-bluesky", 'tr:has-text("Demo Bluesky") button:has(svg.lucide-pencil)'], ["/admin/sso", "sso"], ["/admin/livewalls", "livewalls"], ["/admin/livewalls", "live-wall", openLiveWall],
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
    if (typeof click === "function") await click(page);
    else if (click) {
      await page.locator(click).first().click();
      await page.waitForLoadState("networkidle");
    }
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${out}${lang}-${name}.png` });
    console.log(`${lang}-${name}.png`);
  }
}
await browser.close();
