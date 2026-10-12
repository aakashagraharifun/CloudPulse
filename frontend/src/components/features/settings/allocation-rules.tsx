"use client";

import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/shell/auth";
import { useDataStatus } from "@/components/shell/data-status";
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
  inputClass,
} from "@/components/ui/primitives";
import {
  api,
  errorMessage,
  type AllocationRule,
  type AllocationRuleInput,
  type AllocationRuleMutation,
  type MatchField,
} from "@/lib/api";
import { DIMENSION_LABELS } from "@/lib/format";
import { useApi } from "@/lib/hooks";

const MATCH_FIELDS: MatchField[] = ["service", "resource_id", "account_id", "region", "usage_type", "provider"];

export function AllocationRules() {
  const admin = useAuth().can("admin");
  const rules = useApi<AllocationRule[]>("/allocation-rules");
  const { refresh } = useDataStatus();
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  function done(result: AllocationRuleMutation, verb: string) {
    setMessage({ tone: "success", text: `Rule ${verb}. ${result.records_updated.toLocaleString()} billing record(s) re-attributed.` });
    rules.reload();
    refresh();
  }

  async function toggle(rule: AllocationRule) {
    try {
      const body: AllocationRuleInput = {
        name: rule.name,
        match_field: rule.match_field,
        match_operator: rule.match_operator,
        match_value: rule.match_value,
        project: rule.project,
        environment: rule.environment,
        priority: rule.priority,
        enabled: !rule.enabled,
      };
      done(await api.put<AllocationRuleMutation>(`/allocation-rules/${rule.id}`, body), rule.enabled ? "disabled" : "enabled");
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    }
  }

  return (
    <Card
      title="Cost allocation rules"
      description="Attribute costs that have no project or environment tag. Source tags always win; rules are applied in priority order (lowest first)."
      action={admin && !adding && <Button size="sm" onClick={() => setAdding(true)}>Add rule</Button>}
    >
      {adding && (
        <div className="mb-5">
          <RuleForm
            onCancel={() => setAdding(false)}
            onSaved={(result) => {
              setAdding(false);
              done(result, "created");
            }}
          />
        </div>
      )}
      {message && (
        <div className="mb-4">
          <Notice tone={message.tone}>{message.text}</Notice>
        </div>
      )}
      {rules.error ? (
        <ErrorState message={errorMessage(rules.error)} onRetry={rules.reload} />
      ) : !rules.data ? (
        <LoadingState />
      ) : rules.data.length === 0 ? (
        <EmptyState
          title="No allocation rules"
          description="Example: resources whose ID starts with “nat-” belong to project “platform”, environment “production”."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th scope="col" className="px-4 py-2 font-medium">Priority</th>
                <th scope="col" className="px-3 py-2 font-medium">Rule</th>
                <th scope="col" className="px-3 py-2 font-medium">Match</th>
                <th scope="col" className="px-3 py-2 font-medium">Assigns</th>
                <th scope="col" className="relative px-4 py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rules.data.map((rule) => (
                <tr key={rule.id} className="align-top">
                  <td className="tabular px-4 py-2.5 text-slate-600">{rule.priority}</td>
                  <td className="px-3 py-2.5 font-medium text-slate-900">
                    {rule.name}
                    {!rule.enabled && <Badge tone="warning" className="ml-2">Disabled</Badge>}
                  </td>
                  <td className="px-3 py-2.5 text-slate-600">
                    {DIMENSION_LABELS[rule.match_field]} {rule.match_operator.replace("prefix", "starts with")}{" "}
                    <Mono className="text-slate-900">{rule.match_value}</Mono>
                  </td>
                  <td className="px-3 py-2.5 text-slate-600">
                    {[rule.project && `project ${rule.project}`, rule.environment && `environment ${rule.environment}`].filter(Boolean).join(", ")}
                  </td>
                  <td className="px-4 py-2.5">
                    {admin && (
                    <div className="flex justify-end gap-2">
                      <Button variant="ghost" size="sm" onClick={() => toggle(rule)}>
                        {rule.enabled ? "Disable" : "Enable"}
                      </Button>
                      <DeleteRuleButton rule={rule} onDeleted={(result) => done(result, "deleted")} onError={(text) => setMessage({ tone: "error", text })} />
                    </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function DeleteRuleButton({
  rule,
  onDeleted,
  onError,
}: {
  rule: AllocationRule;
  onDeleted: (result: AllocationRuleMutation) => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  async function remove() {
    if (!window.confirm(`Delete the rule "${rule.name}"? Records it attributed will be re-evaluated.`)) return;
    setBusy(true);
    try {
      // DELETE returns the mutation summary (records re-attributed), so read the body.
      const result = await api.deleteWithBody<AllocationRuleMutation>(`/allocation-rules/${rule.id}`);
      onDeleted(result);
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Button variant="danger" size="sm" disabled={busy} onClick={remove}>
      Delete
    </Button>
  );
}

function RuleForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: (result: AllocationRuleMutation) => void }) {
  const [form, setForm] = useState<AllocationRuleInput>({
    name: "",
    match_field: "resource_id",
    match_operator: "prefix",
    match_value: "",
    project: "",
    environment: "",
    priority: 100,
    enabled: true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!form.project?.trim() && !form.environment?.trim()) {
      setError("Assign a project, an environment, or both.");
      return;
    }
    setBusy(true);
    try {
      onSaved(await api.post<AllocationRuleMutation>("/allocation-rules", { ...form, priority: Number(form.priority) }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
      <Field label="Rule name" htmlFor="r-name" className="sm:col-span-2">
        <input id="r-name" required maxLength={120} className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </Field>
      <Field label="Priority" htmlFor="r-priority" hint="Lower runs first">
        <input id="r-priority" type="number" min="0" max="10000" required className={inputClass} value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })} />
      </Field>
      <div />
      <Field label="Match field" htmlFor="r-field">
        <select id="r-field" className={inputClass} value={form.match_field} onChange={(e) => setForm({ ...form, match_field: e.target.value as MatchField })}>
          {MATCH_FIELDS.map((f) => (
            <option key={f} value={f}>{DIMENSION_LABELS[f]}</option>
          ))}
        </select>
      </Field>
      <Field label="Operator" htmlFor="r-op">
        <select id="r-op" className={inputClass} value={form.match_operator} onChange={(e) => setForm({ ...form, match_operator: e.target.value as AllocationRuleInput["match_operator"] })}>
          <option value="equals">equals</option>
          <option value="prefix">starts with</option>
          <option value="contains">contains</option>
        </select>
      </Field>
      <Field label="Value (case-insensitive)" htmlFor="r-value" className="sm:col-span-2">
        <input id="r-value" required maxLength={512} className={inputClass} value={form.match_value} onChange={(e) => setForm({ ...form, match_value: e.target.value })} />
      </Field>
      <Field label="Assign project" htmlFor="r-project">
        <input id="r-project" maxLength={128} className={inputClass} value={form.project ?? ""} onChange={(e) => setForm({ ...form, project: e.target.value })} />
      </Field>
      <Field label="Assign environment" htmlFor="r-env">
        <input id="r-env" maxLength={128} className={inputClass} value={form.environment ?? ""} onChange={(e) => setForm({ ...form, environment: e.target.value })} />
      </Field>
      {error && (
        <div className="sm:col-span-2 lg:col-span-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      <div className="flex gap-2 sm:col-span-2 lg:col-span-4">
        <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Add rule"}</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
