import path from "node:path";

import { expect, test } from "@playwright/test";

const INVALID_CSV = path.join(__dirname, "..", "..", "sample-data", "invalid_billing_example.csv");

test("an invalid CSV is rejected with line-by-line errors", async ({ page }) => {
  await page.goto("/dashboard/imports");
  await page.setInputFiles('input[type="file"]', INVALID_CSV);
  await page.getByRole("button", { name: "Import file" }).click();
  await expect(page.getByText("was rejected. Nothing was imported.")).toBeVisible();
  const errors = page.getByRole("table").filter({ hasText: "Problem" });
  await expect(errors.getByText("contains a comma")).toBeVisible();
  await expect(errors.getByText("is not an ISO 8601 date")).toBeVisible();
});

test("the overview shows analytics for the sample data", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByText("Sample data").first()).toBeVisible();
  await expect(page.getByText("Spend, month to date")).toBeVisible();
  await expect(page.getByText("Top services")).toBeVisible();
  await expect(page.getByText("Amazon Elastic Compute Cloud").first()).toBeVisible();
});

test("the cost explorer drills down from a breakdown row", async ({ page }) => {
  await page.goto("/dashboard/costs");
  await page.getByRole("button", { name: "Amazon Virtual Private Cloud" }).click();
  await expect(page).toHaveURL(/service=Amazon\+Virtual\+Private\+Cloud|service=Amazon%20Virtual%20Private%20Cloud/);
  await expect(page.getByText("Service: Amazon Virtual Private Cloud").first()).toBeVisible();
  await page.getByLabel("Group by").selectOption("usage_type");
  await expect(page.getByText("NatGateway-Bytes").first()).toBeVisible();
});

test("AI model spend is shown next to cloud spend and drills into the explorer", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByText("Spend by category")).toBeVisible();
  await expect(page.getByText("AI & LLM APIs")).toBeVisible();
  await expect(page.getByRole("link", { name: /Microsoft Azure/ })).toBeVisible();
  await page.getByRole("link", { name: /claude-sonnet-4-5/ }).click();
  await expect(page).toHaveURL(/category=ai/);
  await expect(page).toHaveURL(/model=claude-sonnet-4-5/);
  await expect(page.getByText("Model: claude-sonnet-4-5").first()).toBeVisible();
});
