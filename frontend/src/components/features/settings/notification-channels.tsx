"use client";

import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/shell/auth";
import { HoldToDeleteButton } from "@/components/ui/hold-to-delete";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Mono,
  Notice,
  Pagination,
  inputClass,
} from "@/components/ui/primitives";
import { api, errorMessage, qs, type Channel, type ChannelInput, type Delivery, type Page, type Severity } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

export function NotificationChannels() {
  const admin = useAuth().can("admin");
  const channels = useApi<Channel[]>("/notifications/channels");
  const [offset, setOffset] = useState(0);
  const deliveries = useApi<Page<Delivery>>(`/notifications/deliveries${qs({ limit: 10, offset })}`);
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  function reload() {
    channels.reload();
    deliveries.reload();
  }

  async function test(channel: Channel) {
    setBusyId(channel.id);
    setMessage(null);
    try {
      const delivery = await api.post<Delivery>(`/notifications/channels/${channel.id}/test`);
      setMessage(
        delivery.status === "sent"
          ? { tone: "success", text: `Test message sent to "${channel.name}".` }
          : { tone: "error", text: `Test to "${channel.name}" failed: ${delivery.last_error}` },
      );
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusyId(null);
      reload();
    }
  }

  async function toggle(channel: Channel) {
    setBusyId(channel.id);
    try {
      const body: ChannelInput = { ...channel, target: null, enabled: !channel.enabled };
      await api.put(`/notifications/channels/${channel.id}`, body);
      reload();
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusyId(null);
    }
  }

  async function remove(channel: Channel) {
    try {
      await api.delete(`/notifications/channels/${channel.id}`);
      reload();
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    }
  }

  return (
    <Card
      title="Notifications"
      description="Budget threshold alerts and new incidents are sent to every enabled channel. Failures are recorded and retried; they never block imports or detection."
      action={admin && !adding && <Button size="sm" onClick={() => setAdding(true)}>Add channel</Button>}
    >
      {adding && (
        <div className="mb-5">
          <ChannelForm
            onCancel={() => setAdding(false)}
            onSaved={(name) => {
              setAdding(false);
              setMessage({ tone: "success", text: `Added "${name}". Send a test message to confirm delivery.` });
              reload();
            }}
          />
        </div>
      )}
      {message && (
        <div className="mb-4">
          <Notice tone={message.tone}>{message.text}</Notice>
        </div>
      )}

      {channels.error ? (
        <ErrorState message={errorMessage(channels.error)} onRetry={channels.reload} />
      ) : !channels.data ? (
        <LoadingState />
      ) : channels.data.length === 0 ? (
        <EmptyState
          title="No notification channels"
          description="Add an e-mail address (captured locally by Mailpit at http://127.0.0.1:8025) or a webhook URL."
        />
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {channels.data.map((channel) => (
            <li key={channel.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
                  {channel.name}
                  <Badge>{channel.type === "email" ? "E-mail" : "Webhook"}</Badge>
                  {!channel.enabled && <Badge tone="warning">Disabled</Badge>}
                </p>
                <Mono className="block truncate text-slate-600">{channel.target_display}</Mono>
                <p className="text-xs text-slate-500">
                  {[channel.notify_budget_alerts && "Budget alerts", channel.notify_incidents && `Incidents (${channel.min_severity}+)`]
                    .filter(Boolean)
                    .join(" · ") || "No events selected"}
                </p>
              </div>
              {admin && (
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" size="sm" disabled={busyId === channel.id} onClick={() => test(channel)}>
                  {busyId === channel.id ? "Working…" : "Send test"}
                </Button>
                <Button variant="ghost" size="sm" disabled={busyId === channel.id} onClick={() => toggle(channel)}>
                  {channel.enabled ? "Disable" : "Enable"}
                </Button>
                <HoldToDeleteButton
                  onConfirm={() => remove(channel)}
                  label={`channel "${channel.name}"`}
                  consequence="Its delivery history is kept."
                />
              </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <h3 className="mb-2 mt-6 text-sm font-semibold text-slate-900">Delivery history</h3>
      {deliveries.error ? (
        <ErrorState message={errorMessage(deliveries.error)} onRetry={deliveries.reload} />
      ) : !deliveries.data ? (
        <LoadingState />
      ) : deliveries.data.items.length === 0 ? (
        <p className="text-sm text-slate-500">No notifications sent yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th scope="col" className="px-4 py-2 font-medium">When</th>
                <th scope="col" className="px-3 py-2 font-medium">Channel</th>
                <th scope="col" className="px-3 py-2 font-medium">Message</th>
                <th scope="col" className="px-4 py-2 font-medium">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {deliveries.data.items.map((d) => (
                <tr key={d.id} className="align-top">
                  <td className="whitespace-nowrap px-4 py-2 text-slate-600">{formatDateTime(d.created_at)}</td>
                  <td className="px-3 py-2 text-slate-700">{d.channel_name}</td>
                  <td className="px-3 py-2 text-slate-700 [overflow-wrap:anywhere]">{d.subject}</td>
                  <td className="px-4 py-2">
                    <Badge tone={d.status === "sent" ? "good" : d.status === "failed" ? "critical" : "warning"}>
                      {d.status} · {d.attempts} attempt{d.attempts === 1 ? "" : "s"}
                    </Badge>
                    {d.last_error && <p className="mt-1 text-xs text-red-700">{d.last_error}</p>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4 pb-3">
            <Pagination total={deliveries.data.total} limit={10} offset={offset} onChange={setOffset} />
          </div>
        </div>
      )}
    </Card>
  );
}

function ChannelForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: (name: string) => void }) {
  const [form, setForm] = useState<ChannelInput>({
    name: "",
    type: "email",
    target: "",
    enabled: true,
    notify_budget_alerts: true,
    notify_incidents: true,
    min_severity: "medium",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/notifications/channels", form);
      onSaved(form.name.trim());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
      <Field label="Name" htmlFor="ch-name">
        <input id="ch-name" required maxLength={120} className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </Field>
      <Field label="Type" htmlFor="ch-type">
        <select id="ch-type" className={inputClass} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as ChannelInput["type"] })}>
          <option value="email">E-mail</option>
          <option value="webhook">Webhook (JSON POST)</option>
        </select>
      </Field>
      <Field
        label={form.type === "email" ? "Recipients" : "Webhook URL"}
        htmlFor="ch-target"
        className="sm:col-span-2"
        hint={form.type === "email" ? "Comma-separated addresses" : "http(s) URL; the payload includes a Slack-compatible \"text\" field"}
      >
        <input
          id="ch-target"
          required
          maxLength={2048}
          type={form.type === "webhook" ? "url" : "text"}
          className={inputClass}
          value={form.target ?? ""}
          onChange={(e) => setForm({ ...form, target: e.target.value })}
          placeholder={form.type === "email" ? "team@example.com" : "https://hooks.example.com/…"}
        />
      </Field>
      <div className="flex flex-col gap-2 sm:col-span-2">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" className="size-4 accent-brand-600" checked={form.notify_budget_alerts} onChange={(e) => setForm({ ...form, notify_budget_alerts: e.target.checked })} />
          Budget threshold alerts
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" className="size-4 accent-brand-600" checked={form.notify_incidents} onChange={(e) => setForm({ ...form, notify_incidents: e.target.checked })} />
          New incidents
        </label>
      </div>
      <Field label="Minimum incident severity" htmlFor="ch-severity">
        <select id="ch-severity" className={inputClass} value={form.min_severity} onChange={(e) => setForm({ ...form, min_severity: e.target.value as Severity })}>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
      </Field>
      {error && (
        <div className="sm:col-span-2 lg:col-span-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      <div className="flex gap-2 sm:col-span-2 lg:col-span-4">
        <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Add channel"}</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
