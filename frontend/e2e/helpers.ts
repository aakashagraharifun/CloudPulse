import fs from "node:fs";
import path from "node:path";

import { request, type APIRequestContext, type Locator, type Page } from "@playwright/test";

export const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
export const API_URL = (process.env.E2E_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
export const ADMIN = {
  email: process.env.E2E_ADMIN_EMAIL ?? "e2e-admin@example.com",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-password",
  name: "E2E Admin",
};
export const AUTH_DIR = path.join(__dirname, ".auth");
export const ADMIN_STATE = path.join(AUTH_DIR, "admin.json");
const TOKEN_FILE = path.join(AUTH_DIR, "admin-token.json");

export function saveAdminToken(token: string) {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  fs.writeFileSync(TOKEN_FILE, JSON.stringify({ token }));
}

export function adminToken(): string {
  return (JSON.parse(fs.readFileSync(TOKEN_FILE, "utf8")) as { token: string }).token;
}

/** An API client authenticated as the e2e admin (for test setup and cleanup). */
export async function adminApi(): Promise<APIRequestContext> {
  return request.newContext({
    baseURL: `${API_URL}/api/v1/`,
    extraHTTPHeaders: { Authorization: `Bearer ${adminToken()}` },
  });
}

/** Browser storage state that signs the page in with `token`. */
export function storageStateFor(token: string) {
  return {
    cookies: [],
    origins: [{ origin: new URL(BASE_URL).origin, localStorage: [{ name: "cloudpulse.token", value: token }] }],
  };
}

/** Signs in through the form. `stay` keeps the current URL (e.g. its ?next=). */
export async function signIn(page: Page, email: string, password: string, stay = false) {
  if (!stay) await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

/** Press a "Hold to delete" button for `ms` (3 s or more deletes), then release. */
export async function holdButton(page: Page, button: Locator, ms = 3400) {
  await button.hover();
  await page.mouse.down();
  await page.waitForTimeout(ms);
  await page.mouse.up();
}
