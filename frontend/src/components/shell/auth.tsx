"use client";

import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useSyncExternalStore, type ReactNode } from "react";

import { ErrorState, LoadingState } from "@/components/ui/primitives";
import { ApiError, api, errorMessage, type Role, type User } from "@/lib/api";
import { authToken } from "@/lib/auth-token";
import { useApi } from "@/lib/hooks";

const ROLE_RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2 };
const SERVER = "__server__";
// Marks a deliberate sign-out so the redirect goes to /login without a "next" page.
// Kept in sessionStorage because the guarded subtree remounts when the token changes.
const SIGNED_OUT_FLAG = "cloudpulse.signedOut";

function takeSignedOutFlag(): boolean {
  try {
    const flagged = window.sessionStorage.getItem(SIGNED_OUT_FLAG) === "1";
    window.sessionStorage.removeItem(SIGNED_OUT_FLAG);
    return flagged;
  } catch {
    return false;
  }
}

type AuthContextValue = {
  user: User;
  /** True when the signed-in user has at least this role. */
  can: (role: Role) => boolean;
  signOut: () => Promise<void>;
  reloadUser: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function useToken(): string | null {
  return useSyncExternalStore(authToken.subscribe, authToken.get, () => SERVER);
}

function FullPage({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-md flex-1 px-4 py-24">{children}</div>;
}

/**
 * Guards the dashboard: requires a valid session and provides the current user.
 *
 * The subtree is keyed by the token, so signing in as someone else remounts the
 * whole dashboard: no data or role from the previous session can linger (Next.js
 * keeps recently visited routes mounted in the background).
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const token = useToken();
  return (
    <SessionGate key={token ?? "signed-out"} token={token}>
      {children}
    </SessionGate>
  );
}

function SessionGate({ token, children }: { token: string | null; children: ReactNode }) {
  const router = useRouter();
  const signedOut = token === null;
  const me = useApi<User>(token && token !== SERVER ? "/auth/me" : null);

  useEffect(() => {
    if (!signedOut) return;
    if (takeSignedOutFlag()) {
      router.replace("/login");
      return;
    }
    const next = window.location.pathname + window.location.search;
    router.replace(`/login?next=${encodeURIComponent(next)}`);
  }, [signedOut, router]);

  if (token === SERVER || signedOut) {
    return (
      <FullPage>
        <LoadingState label={signedOut ? "Redirecting to sign in…" : "Loading…"} />
      </FullPage>
    );
  }
  if (me.error && !(me.error instanceof ApiError && me.error.status === 401)) {
    return (
      <FullPage>
        <ErrorState message={errorMessage(me.error)} onRetry={me.reload} />
      </FullPage>
    );
  }
  if (!me.data) {
    return (
      <FullPage>
        <LoadingState label="Checking your session…" />
      </FullPage>
    );
  }

  const user = me.data;
  const value: AuthContextValue = {
    user,
    can: (role) => ROLE_RANK[user.role] >= ROLE_RANK[role],
    reloadUser: me.reload,
    signOut: async () => {
      try {
        await api.post("/auth/logout");
      } catch {
        // The session may already be invalid; signing out locally is still correct.
      }
      try {
        window.sessionStorage.setItem(SIGNED_OUT_FLAG, "1");
      } catch {
        // storage blocked: the redirect simply keeps a "next" parameter
      }
      authToken.set(null); // the guard then navigates to /login
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

/** Renders children only for users with at least `role`; otherwise `fallback`. */
export function RequireRole({
  role,
  children,
  fallback = null,
}: {
  role: Role;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  return useAuth().can(role) ? <>{children}</> : <>{fallback}</>;
}
