import { expect, test } from "@playwright/test";

import { ADMIN, adminApi, holdButton, unique } from "./helpers";

type IncidentPage = { items: { id: number; scope_value: string }[] };

test("an incident is investigated, acknowledged, noted and resolved", async ({ page }) => {
  const api = await adminApi();
  const open = (await (await api.get("incidents?status=open&limit=100")).json()) as IncidentPage;
  test.skip(open.items.length === 0, "No open incident left in this database (tests already ran?)");
  const incident = open.items[0];

  await page.goto(`/dashboard/incidents/${incident.id}`);
  await expect(page.getByText("What the billing data shows")).toBeVisible();
  await expect(page.getByText("Largest contributors to the increase")).toBeVisible();
  await expect(page.getByText("Detection evidence")).toBeVisible();

  await page.getByRole("button", { name: "Acknowledge" }).click();
  await expect(page.getByText(`Acknowledged by ${ADMIN.name}`)).toBeVisible();

  const note = unique("Checked the traffic graphs");
  await page.getByLabel("Note or resolution").fill(note);
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText(note)).toBeVisible();

  await page.getByLabel("Note or resolution").fill("Cause confirmed and fixed.");
  await page.getByRole("button", { name: "Resolve" }).click();
  await expect(page.getByText(`Resolved by ${ADMIN.name}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();
  await api.dispose();
});

test("a budget is created, checked and deleted", async ({ page }) => {
  const name = unique("E2E budget");
  await page.goto("/dashboard/budgets");
  await page.getByRole("button", { name: "New budget" }).first().click();
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Amount").fill("100");
  await page.getByRole("button", { name: "Create budget" }).click();
  await expect(page.getByText(`Saved "${name}"`)).toBeVisible();
  await expect(page.getByRole("heading", { name })).toBeVisible();

  await page.getByRole("button", { name: "Check budgets now" }).click();
  await expect(page.getByText("Budgets checked")).toBeVisible();

  const card = page.locator("section").filter({ has: page.getByRole("heading", { name }) });
  const remove = card.getByRole("button", { name: /Hold for 3 seconds to delete budget/ });
  await expect(remove).toContainText("Hold to delete");
  // Letting go early deletes nothing.
  await holdButton(page, remove, 1000);
  await expect(remove).toContainText("Hold to delete");
  await expect(page.getByRole("heading", { name })).toBeVisible();
  // Holding the full three seconds deletes.
  await holdButton(page, remove);
  await expect(page.getByText(`Deleted "${name}"`)).toBeVisible();
});
