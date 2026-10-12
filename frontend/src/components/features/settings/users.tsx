"use client";

import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/shell/auth";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  LoadingState,
  Notice,
  cx,
  inputClass,
} from "@/components/ui/primitives";
import { api, errorMessage, type Role, type User } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

const ROLE_HELP: Record<Role, string> = {
  viewer: "Can view all data",
  member: "Can also import data, respond to incidents and manage budgets",
  admin: "Full access, including settings, users and the audit log",
};

export function UserManagement() {
  const { user: me } = useAuth();
  const users = useApi<User[]>("/users");
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  async function update(user: User, changes: Partial<Pick<User, "role" | "is_active">>, verb: string) {
    setBusyId(user.id);
    setMessage(null);
    try {
      await api.patch<User>(`/users/${user.id}`, changes);
      setMessage({ tone: "success", text: `${user.name} ${verb}.` });
      users.reload();
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusyId(null);
    }
  }

  async function resetPassword(user: User) {
    const password = window.prompt(
      `New password for ${user.email} (at least 10 characters). Their sessions will be signed out.`,
    );
    if (!password) return;
    setBusyId(user.id);
    setMessage(null);
    try {
      await api.post(`/users/${user.id}/reset-password`, { password });
      setMessage({ tone: "success", text: `Password reset for ${user.name}. Share it with them securely.` });
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Card
      title="Users"
      description="Everyone sees the same workspace data; roles control who can change it."
      action={!adding && <Button size="sm" onClick={() => setAdding(true)}>Add user</Button>}
    >
      {adding && (
        <div className="mb-5">
          <AddUserForm
            onCancel={() => setAdding(false)}
            onSaved={(created) => {
              setAdding(false);
              setMessage({ tone: "success", text: `Added ${created.email}. Share the initial password with them securely.` });
              users.reload();
            }}
          />
        </div>
      )}
      {message && (
        <div className="mb-4">
          <Notice tone={message.tone}>{message.text}</Notice>
        </div>
      )}
      {users.error ? (
        <ErrorState message={errorMessage(users.error)} onRetry={users.reload} />
      ) : !users.data ? (
        <LoadingState />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th scope="col" className="px-4 py-2 font-medium">User</th>
                <th scope="col" className="px-3 py-2 font-medium">Role</th>
                <th scope="col" className="px-3 py-2 font-medium">Last sign-in</th>
                <th scope="col" className="relative px-4 py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.data.map((user) => {
                const self = user.id === me.id;
                return (
                  <tr key={user.id} className={cx("align-top", !user.is_active && "bg-slate-50 text-slate-500")}>
                    <td className="px-4 py-2.5">
                      <span className="font-medium text-slate-900">{user.name}</span>
                      {self && <Badge className="ml-2">You</Badge>}
                      {!user.is_active && <Badge tone="warning" className="ml-2">Deactivated</Badge>}
                      <span className="block text-xs text-slate-500">{user.email}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <label className="sr-only" htmlFor={`role-${user.id}`}>Role for {user.email}</label>
                      <select
                        id={`role-${user.id}`}
                        className={cx(inputClass, "h-8 w-28")}
                        value={user.role}
                        disabled={self || busyId === user.id || !user.is_active}
                        onChange={(e) => update(user, { role: e.target.value as Role }, `is now ${e.target.value}`)}
                        title={self ? "You cannot change your own role" : ROLE_HELP[user.role]}
                      >
                        <option value="viewer">Viewer</option>
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td className="px-3 py-2.5 text-slate-600">{formatDateTime(user.last_login_at)}</td>
                    <td className="px-4 py-2.5">
                      {!self && (
                        <div className="flex justify-end gap-2">
                          <Button variant="ghost" size="sm" disabled={busyId === user.id} onClick={() => resetPassword(user)}>
                            Reset password
                          </Button>
                          <Button
                            variant={user.is_active ? "danger" : "secondary"}
                            size="sm"
                            disabled={busyId === user.id}
                            onClick={() =>
                              user.is_active
                                ? window.confirm(`Deactivate ${user.email}? They are signed out immediately.`) &&
                                  update(user, { is_active: false }, "was deactivated")
                                : update(user, { is_active: true }, "was reactivated")
                            }
                          >
                            {user.is_active ? "Deactivate" : "Reactivate"}
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <ul className="mt-3 space-y-0.5 text-xs text-slate-500">
        {(Object.keys(ROLE_HELP) as Role[]).map((role) => (
          <li key={role}>
            <span className="font-medium capitalize text-slate-700">{role}:</span> {ROLE_HELP[role]}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function AddUserForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: (user: User) => void }) {
  const [form, setForm] = useState({ name: "", email: "", role: "viewer" as Role, password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.post<User>("/users", form));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid grid-cols-1 gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
      <Field label="Name" htmlFor="u-name">
        <input id="u-name" required maxLength={80} className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </Field>
      <Field label="Email" htmlFor="u-email">
        <input id="u-email" type="email" required maxLength={254} className={inputClass} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      </Field>
      <Field label="Role" htmlFor="u-role">
        <select id="u-role" className={inputClass} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
          <option value="viewer">Viewer</option>
          <option value="member">Member</option>
          <option value="admin">Admin</option>
        </select>
      </Field>
      <Field label="Initial password" htmlFor="u-password" hint="At least 10 characters.">
        <input id="u-password" type="password" required minLength={10} maxLength={128} autoComplete="new-password" className={inputClass} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
      </Field>
      {error && (
        <div className="sm:col-span-2 lg:col-span-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      <div className="flex gap-2 sm:col-span-2 lg:col-span-4">
        <Button type="submit" disabled={busy}>{busy ? "Adding…" : "Add user"}</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
