import { expect, test } from "@playwright/test";

import { adminApi, signIn, unique } from "./helpers";

test.describe("role-based access", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a viewer can read but not change data", async ({ page }) => {
    const api = await adminApi();
    const email = `${unique("viewer")}@example.com`;
    const password = "viewer-password-123";
    const created = await api.post("users", { data: { email, name: "E2E Viewer", role: "viewer", password } });
    expect(created.status()).toBe(201);

    await signIn(page, email, password);
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

    await page.goto("/dashboard/imports");
    await expect(page.getByText("You have view-only access")).toBeVisible();
    await expect(page.getByRole("button", { name: "Import file" })).toHaveCount(0);

    await page.goto("/dashboard/incidents");
    await expect(page.getByRole("heading", { name: "Incidents" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Run detection now" })).toHaveCount(0);

    await page.goto("/dashboard/settings");
    await expect(page.getByText("Only admins can change workspace settings")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Users" })).toHaveCount(0);

    // The API enforces the same rule even if the UI were bypassed.
    const token = await page.evaluate(() => window.localStorage.getItem("cloudpulse.token"));
    const viewerApi = await page.context().request.post(
      `${process.env.E2E_API_URL ?? "http://127.0.0.1:8000"}/api/v1/imports/sample`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(viewerApi.status()).toBe(403);
    await api.dispose();
  });
});
