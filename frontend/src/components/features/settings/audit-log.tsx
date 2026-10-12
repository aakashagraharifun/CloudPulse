"use client";

import { useState } from "react";

import { Card, EmptyState, ErrorState, LoadingState, Mono, Pagination, cx, inputClass } from "@/components/ui/primitives";
import { errorMessage, qs, type AuditEvent, type Page } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

const LIMIT = 15;
const ACTIONS = [
  "auth.login",
  "auth.login_failed",
  "auth.logout",
  "auth.setup",
  "auth.password_changed",
  "user.created",
  "user.updated",
  "user.password_reset",
  "import.uploaded",
  "import.sample_loaded",
  "import.deleted",
  "detection.run",
  "detection.settings_updated",
  "budget.created",
  "budget.updated",
  "budget.deleted",
  "channel.created",
  "channel.updated",
  "channel.deleted",
  "allocation_rule.created",
  "allocation_rule.updated",
  "allocation_rule.deleted",
];

function summarize(details: Record<string, unknown> | null): string {
  if (!details) return "";
  return Object.entries(details)
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`)
    .join(" · ");
}

export function AuditLog() {
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const events = useApi<Page<AuditEvent>>(`/audit-events${qs({ action, limit: LIMIT, offset })}`);

  return (
    <Card
      title="Audit log"
      description="Sign-ins, user changes and every change to data or settings, newest first."
      action={
        <label className="flex items-center gap-2 text-xs text-slate-600">
          Action
          <select
            className={cx(inputClass, "h-8 w-52")}
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All actions</option>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
      }
      bodyClassName="p-0"
    >
      {events.error ? (
        <div className="p-5">
          <ErrorState message={errorMessage(events.error)} onRetry={events.reload} />
        </div>
      ) : !events.data ? (
        <div className="p-5">
          <LoadingState />
        </div>
      ) : events.data.items.length === 0 ? (
        <EmptyState title="No matching events" />
      ) : (
        <div className={cx("overflow-x-auto", events.loading && "opacity-60")}>
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th scope="col" className="px-5 py-2.5 font-medium">When</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Who</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Action</th>
                <th scope="col" className="px-5 py-2.5 font-medium">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {events.data.items.map((event) => (
                <tr key={event.id} className="align-top">
                  <td className="whitespace-nowrap px-5 py-2.5 text-slate-600">{formatDateTime(event.created_at)}</td>
                  <td className="px-3 py-2.5 text-slate-800">
                    {event.actor_email ?? "—"}
                    {event.ip_address && <span className="block text-xs text-slate-500">{event.ip_address}</span>}
                  </td>
                  <td className="px-3 py-2.5">
                    <Mono className="text-slate-900">{event.action}</Mono>
                    {event.target_type && (
                      <span className="block text-xs text-slate-500">
                        {event.target_type} #{event.target_id}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-2.5 text-xs text-slate-600 [overflow-wrap:anywhere]">
                    {summarize(event.details)}
                    {event.request_id && <span className="block text-slate-400">request {event.request_id}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-5 pb-4">
            <Pagination total={events.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        </div>
      )}
    </Card>
  );
}
