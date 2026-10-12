import { expect, test } from "@playwright/test";

test.describe("landing page hero", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("shows the product and both calls to action work", async ({ page }) => {
    await page.goto("/");
    const hero = page.locator("section").first();
    await expect(hero.getByRole("heading", { level: 1, name: "Know why your cloud bill changed" })).toBeVisible();

    const screenshot = hero.getByRole("img", { name: /CloudPulse overview dashboard/ });
    await expect(screenshot).toBeVisible();
    expect(await screenshot.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);

    await hero.getByRole("link", { name: "See how it works" }).click();
    await expect(page).toHaveURL(/#how-it-works$/);

    await hero.getByRole("link", { name: "Open the dashboard" }).click();
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard/); // signed out -> sign-in first
  });

  test("content is visible immediately when the user prefers reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const hero = page.locator("section").first();
    // Without the reduced-motion override these start at opacity 0 and animate in.
    for (const locator of [
      hero.getByText("CloudPulse turns cloud, AI and SaaS billing exports"),
      hero.getByRole("link", { name: "Open the dashboard" }),
    ]) {
      const opacity = await locator.evaluate((el) => {
        let node: Element | null = el;
        let value = 1;
        while (node) {
          value *= Number(getComputedStyle(node).opacity);
          node = node.parentElement;
        }
        return value;
      });
      expect(opacity).toBe(1);
    }
  });
});

test.describe("landing page providers", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("hero starts right below the header and the provider strip scrolls right to left", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/");
    const headerBottom = await page.locator("header").evaluate((el) => el.getBoundingClientRect().bottom);
    const titleTop = await page.getByRole("heading", { level: 1 }).evaluate((el) => el.getBoundingClientRect().top);
    expect(titleTop - headerBottom).toBeLessThan(96);
    await expect(page.getByText("Runs locally", { exact: true })).toHaveCount(0); // badge removed

    const strip = page.getByRole("region", { name: /Bring cost data from every provider/ });
    await expect(strip).toBeVisible();
    // One accessible list; the copy that makes the loop seamless is hidden from assistive tech.
    const lists = strip.getByRole("list");
    await expect(lists).toHaveCount(1);
    for (const name of ["AWS", "Google Cloud", "Microsoft Azure", "OpenAI", "Anthropic"]) {
      await expect(lists.getByRole("listitem").filter({ hasText: new RegExp(`^${name}$`) })).toHaveCount(1);
    }
    const track = strip.locator(".marquee-track");
    const x = () => track.evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).m41);
    const before = await x();
    await page.waitForTimeout(500);
    expect(await x()).toBeLessThan(before); // moving left: logos enter from the right
  });

  test("the provider strip is static under reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const strip = page.getByRole("region", { name: /Bring cost data from every provider/ });
    const track = strip.locator(".marquee-track");
    expect(await track.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
    await expect(strip.locator("ul[aria-hidden=true]")).toBeHidden();
    // Wrapped instead of clipped: the last provider is visible without scrolling the strip.
    await strip.scrollIntoViewIfNeeded();
    await expect(strip.getByText("MongoDB Atlas").first()).toBeInViewport({ ratio: 1 });
  });
});
