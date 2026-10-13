import { expect, test } from "@playwright/test";

import { adminApi, unique } from "./helpers";

// No test here calls a provider: verify and sync would leave the machine. Those paths
// are covered by backend tests against mocked provider APIs.
test.describe("live billing connectors", () => {
  test("the Claude connection preview plays through every step", async ({ page }) => {
    await page.goto("/dashboard/connectors");
    const preview = page.locator("section", { hasText: "How connecting Claude works" });
    await expect(preview.getByText("Mock preview")).toBeVisible();
    // The scripted timeline takes ~9s; each finished step announces "(complete)".
    await expect(preview.getByText("(complete)")).toHaveCount(6, { timeout: 30_000 });
    await expect(preview.getByRole("button", { name: "Replay" })).toBeEnabled();
    await expect(preview.getByText("connector saved · next sync in 6 h")).toBeVisible();
  });

  test("an admin connects a source; credentials are never shown again", async ({ page }) => {
    const name = unique("OpenAI org");
    const key = `sk-admin-${unique("e2e")}-0000000000`;
    await page.goto("/dashboard/connectors");
    const sources = page.locator("section", { hasText: "Available sources" });
    for (const source of [
      "AWS Cost and Usage Report",
      "AWS Cost Explorer",
      "OpenAI usage & costs",
      "Anthropic Claude usage & costs",
    ]) {
      await expect(sources.getByRole("heading", { name: source })).toBeVisible();
    }

    await sources.locator("li", { hasText: "OpenAI usage & costs" }).getByRole("button", { name: "Connect" }).click();
    await page.getByRole("radio", { name: "Your own credentials" }).click();
    await page.getByLabel("Name *").fill(name);
    await page.getByLabel("Admin API key *").fill(key);
    await page.getByLabel("Sync schedule").selectOption("0");
    await page.getByRole("button", { name: "Save connector" }).click();

    await expect(page.getByText(`Connected "${name}"`)).toBeVisible();
    const row = page.locator("li", { hasText: name });
    await expect(row.getByText("Never synced")).toBeVisible();
    await expect(row.getByText("Manual syncs only")).toBeVisible();
    await expect(row.getByText(`${key.slice(0, 7)}…${key.slice(-4)}`)).toBeVisible();
    expect(await page.content()).not.toContain(key);

    // Clean up through the API (the UI path asks for confirmation).
    const api = await adminApi();
    const connectors = (await (await api.get("connectors")).json()) as { id: number; name: string }[];
    const created = connectors.find((c) => c.name === name);
    expect(created).toBeDefined();
    expect((await api.delete(`connectors/${created!.id}`)).status()).toBe(204);
    await api.dispose();
  });

  test("sandbox: verify opens the mock authorization window, then the connector is saved", async ({ page }) => {
    const name = unique("Claude sandbox");
    await page.goto("/dashboard/connectors");
    await page
      .locator("section", { hasText: "Available sources" })
      .locator("li", { hasText: "Anthropic Claude usage & costs" })
      .getByRole("button", { name: "Connect" })
      .click();
    await expect(page.getByRole("radio", { name: "Sandbox account" })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByRole("button", { name: "Save connector" })).toBeDisabled();

    const popupPromise = page.waitForEvent("popup");
    await page.getByRole("button", { name: "Verify credentials" }).click();
    const popup = await popupPromise;
    await expect(popup.getByRole("heading", { name: "Connect Anthropic to CloudPulse?" })).toBeVisible();
    await popup.getByRole("button", { name: "Authorize" }).click();
    await expect(popup.getByRole("heading", { name: "Access token accepted" })).toBeVisible();
    await expect(popup.getByText("You can close this window")).toBeVisible();
    await popup.getByRole("button", { name: "Close window" }).click();

    await expect(page.getByText("Access token accepted. Finish the settings and save.")).toBeVisible();
    await page.getByLabel("Name *").fill(name);
    await page.getByLabel("Sync schedule").selectOption("0");
    await page.getByRole("button", { name: "Save connector" }).click();

    const row = page.locator("li", { hasText: name });
    await expect(row.getByText("Sandbox", { exact: true })).toBeVisible();
    await expect(row.getByText("✓ Acme AI (sandbox organization)")).toBeVisible();
    await row.getByRole("button", { name: "Sync now" }).click();
    await expect(row.getByText(/Sandbox sync: the simulated API returned \d+ cost lines/)).toBeVisible();

    const api = await adminApi();
    const connectors = (await (await api.get("connectors")).json()) as { id: number; name: string }[];
    const created = connectors.find((c) => c.name === name);
    expect((await api.delete(`connectors/${created!.id}`)).status()).toBe(204);
    await api.dispose();
  });
});
