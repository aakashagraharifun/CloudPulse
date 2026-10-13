"use client";

import { RefreshCwIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AnthropicPreview } from "@/components/features/connectors/anthropic-preview";
import { ConnectorForm } from "@/components/features/connectors/connector-form";
import { ProviderMark, StepList } from "@/components/features/connectors/flow-stage";
import { useAuth } from "@/components/shell/auth";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  Notice,
  PageHeader,
} from "@/components/ui/primitives";
import {
  api,
  errorMessage,
  type CatalogEntry,
  type Connector,
  type ConnectorCatalog,
  type SyncResponse,
  type VerifyResponse,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Editing = { entry: CatalogEntry; existing: Connector | null } | null;
type Message = { tone: "success" | "error" | "info"; text: string; importId?: number | null };

function schedule(connector: Connector) {
  if (!connector.enabled) return "Disabled";
  if (connector.sync_interval_hours === 0) return "Manual syncs only";
  const every =
    connector.sync_interval_hours === 24
      ? "Daily"
      : connector.sync_interval_hours === 168
        ? "Weekly"
        : `Every ${connector.sync_interval_hours} h`;
  return connector.next_sync_at ? `${every} · next ${formatDateTime(connector.next_sync_at)}` : every;
}

function syncWindow(connector: Connector) {
  if (connector.kind === "aws_cur_s3") {
    const months = Number(connector.config.billing_periods ?? 2);
    return `${months} billing month${months === 1 ? "" : "s"}`;
  }
  return `last ${connector.lookback_days} days`;
}

function SyncBadge({ connector }: { connector: Connector }) {
  switch (connector.last_sync_status) {
    case "running":
      return <Badge tone="brand">Syncing…</Badge>;
    case "succeeded":
      return <Badge tone="good">Synced</Badge>;
    case "failed":
      return <Badge tone="critical">Sync failed</Badge>;
    default:
      return <Badge>Never synced</Badge>;
  }
}

export function ConnectorsPage() {
  const { can } = useAuth();
  const admin = can("admin");
  const member = can("member");
  const catalog = useApi<ConnectorCatalog>("/connectors/catalog");
  const connectors = useApi<Connector[]>("/connectors");
  const [editing, setEditing] = useState<Editing>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const [busy, setBusy] = useState<{ id: number; action: string } | null>(null);
  const [tests, setTests] = useState<Record<number, VerifyResponse>>({});

  const entries = catalog.data?.kinds ?? [];
  const entryFor = (connector: Connector) => entries.find((e) => e.kind === connector.kind);

  async function sync(connector: Connector) {
    setBusy({ id: connector.id, action: "sync" });
    setMessage(null);
    try {
      const result = await api.post<SyncResponse>(`/connectors/${connector.id}/sync`);
      setMessage({
        tone: result.status === "succeeded" ? "success" : "error",
        text: `${connector.name}: ${result.message}`,
        importId: result.import_id,
      });
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusy(null);
      connectors.reload();
    }
  }

  async function test(connector: Connector) {
    setBusy({ id: connector.id, action: "test" });
    try {
      const result = await api.post<VerifyResponse>(`/connectors/${connector.id}/test`);
      setTests((prev) => ({ ...prev, [connector.id]: result }));
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusy(null);
      connectors.reload();
    }
  }

  async function toggle(connector: Connector) {
    setBusy({ id: connector.id, action: "toggle" });
    try {
      await api.put(`/connectors/${connector.id}`, {
        name: connector.name,
        enabled: !connector.enabled,
        config: connector.config,
        sync_interval_hours: connector.sync_interval_hours,
        lookback_days: connector.lookback_days,
        credentials: null,
      });
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusy(null);
      connectors.reload();
    }
  }

  async function remove(connector: Connector) {
    if (
      !window.confirm(
        `Delete "${connector.name}"? Its stored credentials are destroyed. Billing data it already imported is kept (delete those imports on the Imports page).`,
      )
    )
      return;
    try {
      await api.delete(`/connectors/${connector.id}`);
      setMessage({ tone: "success", text: `Deleted "${connector.name}".` });
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      connectors.reload();
    }
  }

  const isBusy = (connector: Connector, action?: string) =>
    busy?.id === connector.id && (action === undefined || busy.action === action);

  return (
    <>
      <PageHeader
        title="Connectors"
        description="Pull billing data straight from AWS, OpenAI and Anthropic on a schedule. Each sync goes through the same validation, allocation rules and anomaly detection as an uploaded file."
        actions={
          <Button variant="secondary" size="sm" onClick={() => { catalog.reload(); connectors.reload(); }}>
            <RefreshCwIcon className="size-3.5" aria-hidden />
            Refresh
          </Button>
        }
      />

      <div className="space-y-6">
        {catalog.data && !catalog.data.encryption_configured && (
          <Notice tone="warning">
            Connectors are disabled until the server has <Mono>CONNECTOR_ENCRYPTION_KEY</Mono> set (credentials are
            only ever stored encrypted). See <Mono>.env.example</Mono>.
          </Notice>
        )}
        {message && (
          <Notice tone={message.tone}>
            {message.text}{" "}
            {message.importId && (
              <Link href="/dashboard/imports" className="font-medium underline">
                View import #{message.importId}
              </Link>
            )}
          </Notice>
        )}

        <AnthropicPreview />

        {editing && (
          <ConnectorForm
            key={`${editing.entry.kind}-${editing.existing?.id ?? "new"}`}
            entry={editing.entry}
            existing={editing.existing}
            onCancel={() => setEditing(null)}
            onSaved={(saved, created) => {
              setEditing(null);
              setMessage({
                tone: "success",
                text: created
                  ? `Connected "${saved.name}". Run a first sync to pull its costs now, or wait for the schedule.`
                  : `Saved "${saved.name}".`,
              });
              connectors.reload();
            }}
          />
        )}

        <Card title="Your connectors" description="Credentials are write-only; only a masked hint is ever shown.">
          {connectors.error ? (
            <ErrorState message={errorMessage(connectors.error)} onRetry={connectors.reload} />
          ) : !connectors.data ? (
            <LoadingState />
          ) : connectors.data.length === 0 ? (
            <EmptyState
              title="No connectors yet"
              description={
                admin
                  ? "Connect a source below. Verify the credentials first: the check is read-only and stores nothing."
                  : "An admin can connect AWS, OpenAI or Anthropic billing here."
              }
            />
          ) : (
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
              {connectors.data.map((connector) => {
                const entry = entryFor(connector);
                const testResult = tests[connector.id];
                return (
                  <li key={connector.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex min-w-0 gap-3">
                        <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                          <ProviderMark provider={connector.provider} className="size-5" />
                        </span>
                        <div className="min-w-0">
                          <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
                            {connector.name}
                            <SyncBadge connector={connector} />
                            {!connector.enabled && <Badge tone="warning">Disabled</Badge>}
                          </p>
                          <p className="text-xs text-slate-500">
                            {entry?.name ?? connector.kind} · {syncWindow(connector)} · {schedule(connector)}
                          </p>
                          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                            <Mono>{connector.credentials_hint}</Mono>
                            {connector.verified_identity && (
                              <span className="text-good-text">✓ {connector.verified_identity}</span>
                            )}
                          </p>
                          {connector.last_sync_message && (
                            <p
                              className={
                                connector.last_sync_status === "failed"
                                  ? "mt-1 text-xs text-red-700 [overflow-wrap:anywhere]"
                                  : "mt-1 text-xs text-slate-600 [overflow-wrap:anywhere]"
                              }
                            >
                              {connector.last_sync_finished_at && `${formatDateTime(connector.last_sync_finished_at)}: `}
                              {connector.last_sync_message}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {member && (
                          <Button size="sm" disabled={busy !== null} onClick={() => sync(connector)}>
                            {isBusy(connector, "sync") ? "Syncing…" : "Sync now"}
                          </Button>
                        )}
                        {admin && (
                          <>
                            <Button variant="secondary" size="sm" disabled={busy !== null} onClick={() => test(connector)}>
                              {isBusy(connector, "test") ? "Testing…" : "Test"}
                            </Button>
                            {entry && (
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={busy !== null}
                                onClick={() => setEditing({ entry, existing: connector })}
                              >
                                Edit
                              </Button>
                            )}
                            <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => toggle(connector)}>
                              {connector.enabled ? "Disable" : "Enable"}
                            </Button>
                            <Button variant="danger" size="sm" disabled={busy !== null} onClick={() => remove(connector)}>
                              Delete
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                    {testResult && (
                      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                        <StepList
                          steps={testResult.steps.map((s) => ({
                            key: s.key,
                            title: s.label,
                            detail: s.detail,
                            state: s.status === "ok" ? "done" : s.status === "failed" ? "failed" : "skipped",
                          }))}
                        />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card
          title="Available sources"
          description="Each source is read-only: CloudPulse only ever calls billing and identity endpoints."
        >
          {catalog.error ? (
            <ErrorState message={errorMessage(catalog.error)} onRetry={catalog.reload} />
          ) : !catalog.data ? (
            <LoadingState />
          ) : (
            <ul className="grid gap-4 md:grid-cols-2">
              {entries.map((entry) => (
                <li key={entry.kind} className="flex flex-col rounded-xl border border-slate-200 p-4">
                  <div className="flex items-start gap-3">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-ink text-white">
                      <ProviderMark provider={entry.provider} className="size-5" />
                    </span>
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold text-slate-900">{entry.name}</h3>
                      <p className="mt-0.5 text-sm text-slate-600">{entry.tagline}</p>
                    </div>
                  </div>
                  <dl className="mt-3 space-y-1 text-xs text-slate-500">
                    <div>
                      <dt className="inline font-medium text-slate-700">Auth: </dt>
                      <dd className="inline">{entry.auth}</dd>
                    </div>
                    <div>
                      <dt className="inline font-medium text-slate-700">Needs: </dt>
                      <dd className="inline">{entry.permissions.join(", ")}</dd>
                    </div>
                  </dl>
                  <div className="mt-auto pt-4">
                    {admin ? (
                      <Button
                        size="sm"
                        disabled={!catalog.data?.encryption_configured}
                        onClick={() => {
                          setEditing({ entry, existing: null });
                          setMessage(null);
                        }}
                      >
                        Connect
                      </Button>
                    ) : (
                      <p className="text-xs text-slate-500">Ask an admin to connect this source.</p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
