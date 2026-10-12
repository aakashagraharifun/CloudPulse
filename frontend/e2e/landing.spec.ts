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
      hero.getByText("CloudPulse turns billing exports"),
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
