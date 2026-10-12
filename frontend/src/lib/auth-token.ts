/**
 * The session token, kept in localStorage so a page reload keeps you signed in.
 *
 * Trade-off (documented in docs/architecture.md): localStorage is readable by
 * scripts on this origin, so the app never renders untrusted HTML; the token is
 * opaque, expires (12 h by default) and is revoked on sign-out.
 */

const TOKEN_KEY = "cloudpulse.token";
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

export const authToken = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    try {
      return window.localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string | null): void {
    try {
      if (token) window.localStorage.setItem(TOKEN_KEY, token);
      else window.localStorage.removeItem(TOKEN_KEY);
    } catch {
      // storage blocked: the session simply won't survive a reload
    }
    notify();
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    const onStorage = (event: StorageEvent) => {
      if (event.key === TOKEN_KEY) listener();
    };
    window.addEventListener("storage", onStorage);
    return () => {
      listeners.delete(listener);
      window.removeEventListener("storage", onStorage);
    };
  },
};

/** Where to send the user after signing in; only same-app dashboard paths are allowed. */
export function safeNextPath(next: string | null | undefined): string {
  if (next && next.startsWith("/dashboard") && !next.startsWith("//")) return next;
  return "/dashboard";
}
