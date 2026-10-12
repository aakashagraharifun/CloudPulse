"use client";

import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/shell/auth";
import { Badge, Button, Card, Field, Notice, inputClass } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";

export function AccountSettings() {
  const { user } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    if (next !== confirm) {
      setMessage({ tone: "error", text: "The new passwords do not match." });
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setConfirm("");
      setMessage({ tone: "success", text: "Password changed. Your other sessions were signed out." });
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Your account" description={`${user.name} · ${user.email}`} action={<Badge className="capitalize">{user.role}</Badge>}>
      <form onSubmit={submit} className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field label="Current password" htmlFor="pw-current">
          <input id="pw-current" type="password" required autoComplete="current-password" className={inputClass} value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        <Field label="New password" htmlFor="pw-new" hint="At least 10 characters.">
          <input id="pw-new" type="password" required minLength={10} maxLength={128} autoComplete="new-password" className={inputClass} value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Field label="Confirm new password" htmlFor="pw-confirm">
          <input id="pw-confirm" type="password" required maxLength={128} autoComplete="new-password" className={inputClass} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        {message && (
          <div className="sm:col-span-3">
            <Notice tone={message.tone}>{message.text}</Notice>
          </div>
        )}
        <div className="sm:col-span-3">
          <Button type="submit" variant="secondary" disabled={busy}>
            {busy ? "Changing…" : "Change password"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
