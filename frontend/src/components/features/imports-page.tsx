"use client";

import Link from "next/link";
import { useRef, useState, type DragEvent, type FormEvent } from "react";

import { LoadSampleButton } from "@/components/features/load-sample-button";
import { useAuth } from "@/components/shell/auth";
import { useDataStatus } from "@/components/shell/data-status";
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
  Pagination,
  buttonClass,
  cx,
} from "@/components/ui/primitives";
import { API_BASE_URL } from "@/lib/config";
import {
  ApiError,
  api,
  errorMessage,
  qs,
  type ImportDetail,
  type ImportSchema,
  type ImportSummary,
  type Page,
} from "@/lib/api";
import { formatBytes, formatDateRange, formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

const LIMIT = 10;

type Outcome =
  | { kind: "success"; result: ImportDetail }
  | { kind: "invalid"; result: ImportDetail }
  | { kind: "error"; message: string };

function isImportDetail(value: unknown): value is ImportDetail {
  return typeof value === "object" && value !== null && "status" in value && "rows_total" in value;
}

export function ImportsPage() {
  const { refresh } = useDataStatus();
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const imports = useApi<Page<ImportSummary>>(`/imports${qs({ limit: LIMIT, offset })}`);
  const schema = useApi<ImportSchema>("/imports/schema");
  const [file, setFile] = useState<File | null>(null);
  const [isSample, setIsSample] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const maxBytes = schema.data?.max_upload_bytes;

  function choose(selected: File | null) {
    setOutcome(null);
    if (!selected) return setFile(null);
    if (!selected.name.toLowerCase().endsWith(".csv")) {
      setFile(null);
      setOutcome({ kind: "error", message: `"${selected.name}" is not a .csv file.` });
      return;
    }
    if (maxBytes && selected.size > maxBytes) {
      setFile(null);
      setOutcome({ kind: "error", message: `"${selected.name}" is ${formatBytes(selected.size)}; the limit is ${formatBytes(maxBytes)}.` });
      return;
    }
    setFile(selected);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files[0] ?? null);
  }

  function afterImport(result: ImportDetail) {
    setOutcome({ kind: "success", result });
    setOffset(0);
    imports.reload();
    refresh();
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("is_sample", String(isSample));
    setUploading(true);
    setOutcome(null);
    try {
      const result = await api.post<ImportDetail>("/imports", form);
      afterImport(result);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      if (err instanceof ApiError && err.code === "import_validation_failed" && isImportDetail(err.details)) {
        setOutcome({ kind: "invalid", result: err.details });
        imports.reload();
      } else {
        setOutcome({ kind: "error", message: errorMessage(err) });
      }
    } finally {
      setUploading(false);
    }
  }

  async function remove(item: ImportSummary) {
    const what = item.status === "completed" ? ` and its ${item.rows_inserted.toLocaleString()} billing records` : "";
    if (!window.confirm(`Delete import #${item.id} (${item.filename})${what}? Analytics will no longer include this data.`)) return;
    try {
      await api.delete(`/imports/${item.id}`);
      imports.reload();
      refresh();
    } catch (err) {
      setOutcome({ kind: "error", message: errorMessage(err) });
    }
  }

  return (
    <>
      <PageHeader
        title="Imports"
        description="Upload billing exports as CSV. Every row is validated; a file with any invalid row is rejected with line-by-line errors and nothing is imported."
        actions={
          <a href={`${API_BASE_URL}/api/v1/imports/template.csv`} className={buttonClass("secondary")} download>
            Download CSV template
          </a>
        }
      />

      {!can("member") && (
        <div className="mb-4">
          <Notice tone="info">You have view-only access. Members and admins can import billing data.</Notice>
        </div>
      )}
      {can("member") && (
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Upload a billing CSV">
          <form onSubmit={upload} className="space-y-4">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cx(
                "flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-10 text-center transition-colors",
                dragging ? "border-brand-600 bg-brand-50" : "border-slate-300 bg-slate-50",
              )}
            >
              <p className="text-sm font-medium text-slate-900">
                {file ? file.name : "Drag a .csv file here"}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {file
                  ? formatBytes(file.size)
                  : `UTF-8 CSV${maxBytes ? `, up to ${formatBytes(maxBytes)}` : ""}. AWS Cost and Usage Report column names are recognised.`}
              </p>
              <label className={cx(buttonClass("secondary", "sm"), "mt-4 cursor-pointer")}>
                {file ? "Choose a different file" : "Browse files"}
                <input
                  ref={inputRef}
                  type="file"
                  accept=".csv,text/csv"
                  className="sr-only"
                  onChange={(e) => choose(e.target.files?.[0] ?? null)}
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="size-4 accent-brand-600"
                  checked={isSample}
                  onChange={(e) => setIsSample(e.target.checked)}
                />
                This file contains synthetic / sample data
              </label>
              <Button type="submit" disabled={!file || uploading}>
                {uploading ? "Validating and importing…" : "Import file"}
              </Button>
            </div>
          </form>

          {outcome && (
            <div className="mt-4">
              <ImportOutcome outcome={outcome} />
            </div>
          )}
        </Card>

        <Card title="No data handy?" description="A deterministic 90-day synthetic dataset">
          <p className="mb-4 text-sm text-slate-600">
            Multi-service AWS and GCP costs in USD with two injected anomalies: a NAT gateway data-transfer spike and a
            new GPU instance. It is labelled as sample data everywhere it appears.
          </p>
          <LoadSampleButton variant="secondary" onLoaded={afterImport} />
        </Card>
      </div>
      )}

      <Card className="mt-4" title="Import history" bodyClassName="p-0">
        {imports.error ? (
          <div className="p-5">
            <ErrorState message={errorMessage(imports.error)} onRetry={imports.reload} />
          </div>
        ) : !imports.data ? (
          <div className="p-5">
            <LoadingState rows={4} />
          </div>
        ) : imports.data.items.length === 0 ? (
          <EmptyState title="No imports yet" description="Upload a CSV or load the sample dataset to get started." />
        ) : (
          <div className={cx("overflow-x-auto", imports.loading && "opacity-60")}>
            <table className="w-full min-w-[820px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th scope="col" className="px-5 py-2.5 font-medium">File</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Status</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">Rows</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">Imported</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">Duplicates skipped</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Billing dates</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Uploaded</th>
                  <th scope="col" className="relative px-5 py-2.5"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {imports.data.items.map((item) => (
                  <tr key={item.id} className="align-top">
                    <td className="max-w-xs px-5 py-3">
                      <span className="block truncate font-medium text-slate-900" title={item.filename}>
                        {item.filename}
                      </span>
                      <span className="mt-1 flex flex-wrap gap-1">
                        <span className="text-xs text-slate-500">#{item.id} · {formatBytes(item.file_size_bytes)}</span>
                        {item.source === "sample" && <Badge tone="sample">Sample data</Badge>}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <Badge tone={item.status === "completed" ? "good" : item.status === "failed" ? "critical" : "warning"}>
                        {item.status}
                      </Badge>
                      {item.error_summary && (
                        <p className="mt-1 max-w-56 text-xs text-slate-600">{item.error_summary}</p>
                      )}
                    </td>
                    <td className="tabular px-3 py-3 text-right">{item.rows_total.toLocaleString()}</td>
                    <td className="tabular px-3 py-3 text-right">{item.rows_inserted.toLocaleString()}</td>
                    <td className="tabular px-3 py-3 text-right">{item.rows_duplicate.toLocaleString()}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-slate-600">
                      {item.date_start && item.date_end ? formatDateRange(item.date_start, item.date_end) : "—"}
                      {item.currencies && <span className="block text-xs">{item.currencies.join(", ")}</span>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-slate-600">{formatDateTime(item.created_at)}</td>
                    <td className="px-5 py-3 text-right">
                      {can("admin") && item.status !== "processing" && (
                        <Button variant="danger" size="sm" onClick={() => remove(item)}>
                          Delete
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="px-5 pb-4">
              <Pagination total={imports.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
            </div>
          </div>
        )}
      </Card>

      <Card className="mt-4" title="Canonical billing format" description="Header names are matched case-insensitively; punctuation and spaces are ignored." bodyClassName="p-0">
        {schema.error ? (
          <div className="p-5">
            <ErrorState message={errorMessage(schema.error)} onRetry={schema.reload} />
          </div>
        ) : !schema.data ? (
          <div className="p-5">
            <LoadingState />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th scope="col" className="px-5 py-2.5 font-medium">Field</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Description</th>
                  <th scope="col" className="px-5 py-2.5 font-medium">Accepted column names</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {schema.data.fields.map((field) => (
                  <tr key={field.name} className="align-top">
                    <td className="whitespace-nowrap px-5 py-3">
                      <Mono className="font-medium text-slate-900">{field.name}</Mono>
                      {field.required && <Badge tone="brand" className="ml-2">Required</Badge>}
                    </td>
                    <td className="px-3 py-3 text-slate-600">
                      {field.description}
                      <span className="mt-1 block text-xs text-slate-500">
                        Example: <Mono>{field.example}</Mono>
                      </span>
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-600">
                      <Mono className="text-xs">{field.accepted_headers.join(", ")}</Mono>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function ImportOutcome({ outcome }: { outcome: Outcome }) {
  if (outcome.kind === "error") return <Notice tone="error">{outcome.message}</Notice>;
  const r = outcome.result;
  if (outcome.kind === "success") {
    return (
      <Notice tone="success">
        <p className="font-medium">
          Imported {r.rows_inserted.toLocaleString()} new record(s) from {r.filename}.
        </p>
        <p className="mt-1">
          {r.rows_total.toLocaleString()} row(s) read
          {r.rows_duplicate > 0 && ` · ${r.rows_duplicate.toLocaleString()} already-imported record(s) skipped as duplicates`}
          {r.date_start && r.date_end && ` · billing dates ${formatDateRange(r.date_start, r.date_end)}`}
          {r.currencies && ` · ${r.currencies.join(", ")}`}. Anomaly detection and budget checks ran automatically.
        </p>
        <p className="mt-2 flex flex-wrap gap-3">
          <Link href="/dashboard" className="font-medium underline">View overview</Link>
          <Link href="/dashboard/incidents" className="font-medium underline">View incidents</Link>
        </p>
      </Notice>
    );
  }
  return (
    <div className="space-y-3">
      <Notice tone="error">
        <p className="font-medium">{r.filename} was rejected. Nothing was imported.</p>
        <p className="mt-1">{r.error_summary}</p>
      </Notice>
      {r.errors && r.errors.length > 0 && (
        <div className="max-h-80 overflow-auto rounded-lg border border-slate-200">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-50">
              <tr className="text-left text-xs text-slate-500">
                <th scope="col" className="px-4 py-2 font-medium">Line</th>
                <th scope="col" className="px-3 py-2 font-medium">Column</th>
                <th scope="col" className="px-4 py-2 font-medium">Problem</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {r.errors.map((e, i) => (
                <tr key={`${e.line}-${e.column}-${i}`} className="align-top">
                  <td className="tabular px-4 py-2 text-slate-700">{e.line ?? "—"}</td>
                  <td className="px-3 py-2"><Mono>{e.column ?? "row"}</Mono></td>
                  <td className="px-4 py-2 text-slate-700 [overflow-wrap:anywhere]">{e.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
