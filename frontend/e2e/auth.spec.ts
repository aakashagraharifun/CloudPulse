import { expect, test } from "@playwright/test";

import { ADMIN, signIn } from "./helpers";

test.describe("authentication", () => {
  test.use({ storageState: { cookies: [], origins: [] } }); // start signed out

  test("dashboard redirects to sign-in and back after login", async ({ page }) => {
    await page.goto("/dashboard/costs");
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard%2Fcosts/);
    await expect(page.getByRole("heading", { name: "Sign in to CloudPulse" })).toBeVisible();

    await signIn(page, ADMIN.email, "definitely-wrong-password", true);
    await expect(page.getByText("Email or password is incorrect.")).toBeVisible();

    await signIn(page, ADMIN.email, ADMIN.password, true);
    await expect(page).toHaveURL(/\/dashboard\/costs$/);
    await expect(page.getByRole("heading", { name: "Cost explorer" })).toBeVisible();
  });

  test("sign out ends the session", async ({ page }) => {
    await signIn(page, ADMIN.email, ADMIN.password);
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).first().click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login\?next=/);
  });

  test("an open redirect via ?next is not possible", async ({ page }) => {
    await page.goto("/login?next=https://example.com");
    await page.getByLabel("Email").fill(ADMIN.email);
    await page.getByLabel("Password", { exact: true }).fill(ADMIN.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });
});

test.describe("first-run setup", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("an empty workspace asks for the admin account", async ({ page }) => {
    // Simulate an empty database without touching the real one.
    await page.route("**/api/v1/auth/status", (route) => route.fulfill({ json: { setup_required: true } }));
    let setupBody: unknown = null;
    await page.route("**/api/v1/auth/setup", async (route) => {
      setupBody = route.request().postDataJSON();
      await route.fulfill({ status: 409, json: { error: { code: "conflict", message: "Setup has already been completed. Sign in instead.", details: null } } });
    });

    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Create the admin account" })).toBeVisible();
    await page.getByLabel("Name").fill("First Admin");
    await page.getByLabel("Email").fill("first@example.com");
    await page.getByLabel("Password", { exact: true }).fill("first-admin-password");
    await page.getByLabel("Confirm password").fill("does-not-match-1");
    await page.getByRole("button", { name: "Create admin account" }).click();
    await expect(page.getByText("The passwords do not match.")).toBeVisible();

    await page.getByLabel("Confirm password").fill("first-admin-password");
    await page.getByRole("button", { name: "Create admin account" }).click();
    await expect(page.getByText("Setup has already been completed")).toBeVisible();
    expect(setupBody).toEqual({ name: "First Admin", email: "first@example.com", password: "first-admin-password" });
  });
});
