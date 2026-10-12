import fs from "node:fs";

import { request } from "@playwright/test";

import { ADMIN, ADMIN_STATE, API_URL, AUTH_DIR, saveAdminToken, storageStateFor } from "./helpers";

/**
 * Signs in the e2e admin (creating it through first-run setup on an empty
 * database), makes sure the sample dataset is loaded, and stores the browser
 * state every test starts from.
 */
export default async function globalSetup() {
  const api = await request.newContext({ baseURL: `${API_URL}/api/v1/` });
  const ready = await api.get("ready");
  if (!ready.ok()) {
    throw new Error(`The API at ${API_URL} is not ready (${ready.status()}). Start the stack first.`);
  }

  const status = (await (await api.get("auth/status")).json()) as { setup_required: boolean };
  const response = status.setup_required
    ? await api.post("auth/setup", { data: ADMIN })
    : await api.post("auth/login", { data: { email: ADMIN.email, password: ADMIN.password } });
  if (!response.ok()) {
    throw new Error(
      `Could not sign in the e2e admin ${ADMIN.email} (${response.status()}: ${await response.text()}). ` +
        "Run the tests against an empty database, or set E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD.",
    );
  }
  const { token } = (await response.json()) as { token: string };
  saveAdminToken(token);

  const authed = await request.newContext({
    baseURL: `${API_URL}/api/v1/`,
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  });
  const sample = await authed.post("imports/sample");
  if (!sample.ok() && sample.status() !== 409) {
    throw new Error(`Loading sample data failed: ${sample.status()} ${await sample.text()}`);
  }

  fs.mkdirSync(AUTH_DIR, { recursive: true });
  fs.writeFileSync(ADMIN_STATE, JSON.stringify(storageStateFor(token)));
  await api.dispose();
  await authed.dispose();
}
