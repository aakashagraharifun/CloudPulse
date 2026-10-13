"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { CheckIcon, FlaskConicalIcon, XIcon } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useRef, useState, useSyncExternalStore } from "react";

import { Logo } from "@/components/brand/logo";
import { FlowStage, PROVIDER_LABEL } from "@/components/features/connectors/flow-stage";
import { Badge, Button, Notice } from "@/components/ui/primitives";
import { authToken } from "@/lib/auth-token";
import {
  api,
  errorMessage,
  type ConnectorKind,
  type SandboxAuthMessage,
  type SandboxAuthorizeResponse,
} from "@/lib/api";

gsap.registerPlugin(useGSAP, MotionPathPlugin);

const noSubscription = () => () => {};

const KINDS: Record<ConnectorKind, { provider: string; name: string; account: string; grants: string[] }> = {
  anthropic_costs: {
    provider: "anthropic",
    name: "Anthropic Claude usage & costs",
    account: "Acme AI (sandbox organization)",
    grants: ["Read the organization's daily cost report", "Read workspace names"],
  },
  openai_costs: {
    provider: "openai",
    name: "OpenAI usage & costs",
    account: "Acme AI (sandbox organization)",
    grants: ["Read organization costs", "Read project names"],
  },
  aws_cost_explorer: {
    provider: "aws",
    name: "AWS Cost Explorer",
    account: "AWS account 123456789012 (sandbox)",
    grants: ["Read the account identity (sts:GetCallerIdentity)", "Read daily costs (ce:GetCostAndUsage)"],
  },
  aws_cur_s3: {
    provider: "aws",
    name: "AWS Cost and Usage Report",
    account: "AWS account 123456789012 (sandbox)",
    grants: ["Read the account identity (sts:GetCallerIdentity)", "List and read CUR files in S3"],
  },
};

type Phase = "consent" | "authorizing" | "done" | "error";

/**
 * The window "Verify credentials" opens in sandbox mode: a simulated consent
 * screen for a provider account. It is CloudPulse's own page (no provider is
 * contacted); on approval it asks the API for a sandbox token and hands it
 * back to the connect form with postMessage, restricted to this origin.
 */
export function SandboxAuthorize() {
  const params = useSearchParams();
  const kind = params.get("kind") as ConnectorKind | null;
  const state = params.get("state") ?? "";
  const info = kind ? KINDS[kind] : undefined;
  const scope = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>("consent");
  const [identity, setIdentity] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Browser-only facts, read via useSyncExternalStore so the server render (which
  // can't know them) and hydration agree; they settle right after hydration.
  const signedIn = useSyncExternalStore(authToken.subscribe, () => authToken.get() !== null, () => null);
  const hasOpener = useSyncExternalStore(noSubscription, () => Boolean(window.opener), () => false);

  useGSAP(
    () => {
      const root = scope.current;
      const wire = root?.querySelector<SVGPathElement>("[data-flow=wire]");
      if (!root || !wire) return;
      const q = gsap.utils.selector(root);
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const d = (seconds: number) => (reduce ? 0 : seconds);
      const travel = (target: Element, reverse: boolean) => ({
        motionPath: { path: wire, align: wire, alignOrigin: [0.5, 0.5] as [number, number], start: reverse ? 1 : 0, end: reverse ? 0 : 1 },
        duration: d(0.7),
        ease: "power1.inOut",
        immediateRender: false,
        onStart: () => {
          gsap.set(target, { opacity: reduce ? 0 : 1 });
        },
        onComplete: () => {
          gsap.set(target, { opacity: 0 });
        },
      });

      if (phase === "consent") {
        gsap.from(q("[data-sandbox=card]"), { opacity: 0, y: 16, duration: d(0.5), ease: "power2.out" });
        gsap.from(q("[data-sandbox=grant]"), { opacity: 0, x: -8, duration: d(0.35), stagger: 0.08, delay: d(0.2) });
      }
      if (phase === "authorizing") {
        const length = wire.getTotalLength();
        gsap.set(wire, { strokeDasharray: length, strokeDashoffset: length, opacity: 1 });
        const tl = gsap.timeline();
        tl.to(wire, { strokeDashoffset: 0, duration: d(0.6), ease: "power2.out" });
        if (!reduce) {
          const loop = gsap.timeline({ repeat: -1 });
          loop.to(q("[data-flow=packet]")[0], travel(q("[data-flow=packet]")[0], false));
          tl.add(loop);
        }
      }
      if (phase === "done") {
        gsap.set(wire, { strokeDasharray: "none", opacity: 1, stroke: "#3987e5" });
        const reply = q("[data-flow=reply]")[0];
        gsap
          .timeline()
          .to(reply, travel(reply, true))
          .to(wire, { stroke: "#1baf7a", duration: d(0.4) })
          .fromTo(q("[data-flow=badge-ok]"), { opacity: 0, scale: 0 }, { opacity: 1, scale: 1, duration: d(0.4), ease: "back.out(3)" }, "<")
          .fromTo(q("[data-flow=identity]"), { opacity: 0 }, { opacity: 1, duration: d(0.3) }, "<")
          .fromTo(q("[data-sandbox=success]"), { opacity: 0, scale: 0.94 }, { opacity: 1, scale: 1, duration: d(0.45), ease: "back.out(2)" }, "-=0.1")
          .fromTo(q("[data-sandbox=check]"), { scale: 0, rotate: -45 }, { scale: 1, rotate: 0, duration: d(0.5), ease: "back.out(3)" }, "<0.1");
      }
      if (phase === "error") {
        gsap.set(wire, { strokeDasharray: "none", opacity: 1, stroke: "#d03b3b" });
        gsap.fromTo(q("[data-flow=badge-fail]"), { opacity: 0, scale: 0 }, { opacity: 1, scale: 1, duration: d(0.35) });
      }
    },
    { scope, dependencies: [phase], revertOnUpdate: true },
  );

  function post(message: SandboxAuthMessage) {
    // Only the CloudPulse page that opened this window (same origin) may receive the token.
    window.opener?.postMessage(message, window.location.origin);
  }

  async function authorize() {
    if (!kind) return;
    setPhase("authorizing");
    setError(null);
    try {
      const [result] = await Promise.all([
        api.post<SandboxAuthorizeResponse>("/connectors/sandbox/authorize", { kind }),
        new Promise((resolve) => setTimeout(resolve, 1200)), // let the handshake play
      ]);
      setIdentity(result.identity);
      post({ source: "cloudpulse-sandbox-auth", state, kind, status: "authorized", token: result.token, identity: result.identity });
      setPhase("done");
    } catch (err) {
      setError(errorMessage(err));
      setPhase("error");
    }
  }

  function cancel() {
    if (kind) post({ source: "cloudpulse-sandbox-auth", state, kind, status: "cancelled" });
    window.close();
  }

  if (!info || !kind) {
    return (
      <Shell>
        <Notice tone="error">This authorization link is incomplete. Start again from the Connectors page.</Notice>
      </Shell>
    );
  }

  return (
    <Shell>
      <div ref={scope}>
        <div data-sandbox="card" className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl shadow-slate-900/5">
          <div className="p-4">
            <FlowStage provider={info.provider} remoteCaption="Sandbox" identity={identity ?? info.account} />
          </div>

          {phase === "done" ? (
            <div data-sandbox="success" className="px-6 pb-6 pt-2 text-center">
              <span
                data-sandbox="check"
                className="mx-auto mb-3 flex size-14 items-center justify-center rounded-full bg-good text-white shadow-[0_0_32px_rgba(12,163,12,0.45)]"
              >
                <CheckIcon className="size-7" strokeWidth={3} aria-hidden />
              </span>
              <h1 className="text-lg font-semibold text-slate-900">Access token accepted</h1>
              <p className="mt-1 text-sm text-slate-600">
                CloudPulse is authorized for <span className="font-medium text-slate-900">{identity}</span>.
              </p>
              <p className="mt-3 text-sm text-slate-600">
                {hasOpener
                  ? "You can close this window and finish setting up the connector in CloudPulse."
                  : "Return to the CloudPulse tab to finish setting up the connector."}
              </p>
              <Button className="mt-5 w-full" onClick={() => window.close()}>
                Close window
              </Button>
            </div>
          ) : (
            <div className="px-6 pb-6 pt-2">
              <h1 className="text-lg font-semibold text-slate-900">
                Connect {PROVIDER_LABEL[info.provider] ?? info.provider} to CloudPulse?
              </h1>
              <p className="mt-1 text-sm text-slate-600">
                CloudPulse requests read-only access to <span className="font-medium text-slate-900">{info.account}</span>{" "}
                for the <span className="font-medium text-slate-900">{info.name}</span> connector.
              </p>
              <ul className="mt-4 space-y-2">
                {info.grants.map((grant) => (
                  <li key={grant} data-sandbox="grant" className="flex items-start gap-2 text-sm text-slate-700">
                    <CheckIcon className="mt-0.5 size-4 shrink-0 text-good-text" aria-hidden />
                    {grant}
                  </li>
                ))}
                <li data-sandbox="grant" className="flex items-start gap-2 text-sm text-slate-700">
                  <XIcon className="mt-0.5 size-4 shrink-0 text-red-600" aria-hidden />
                  Never create, change or delete anything
                </li>
              </ul>
              <div className="mt-4 flex gap-2 rounded-lg bg-violet-50 p-3 text-xs text-violet-900 ring-1 ring-inset ring-violet-200">
                <FlaskConicalIcon className="size-4 shrink-0" aria-hidden />
                <p>
                  This is a simulated account for trying CloudPulse. No {PROVIDER_LABEL[info.provider] ?? "provider"} account is
                  contacted, and sandbox syncs never import billing data.
                </p>
              </div>
              {signedIn === false && (
                <div className="mt-4">
                  <Notice tone="warning">Sign in to CloudPulse in this browser first, then try again.</Notice>
                </div>
              )}
              {error && (
                <div className="mt-4">
                  <Notice tone="error">{error}</Notice>
                </div>
              )}
              <div className="mt-5 flex gap-2">
                <Button className="flex-1" onClick={authorize} disabled={!signedIn || phase === "authorizing"}>
                  {phase === "authorizing" ? "Authorizing…" : phase === "error" ? "Try again" : "Authorize"}
                </Button>
                <Button variant="secondary" onClick={cancel} disabled={phase === "authorizing"}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-dvh bg-slate-50 px-4 py-6">
      <div className="mx-auto w-full max-w-md">
        <div className="mb-4 flex items-center justify-between">
          <Logo />
          <Badge tone="sample">Sandbox authorization</Badge>
        </div>
        {children}
      </div>
    </main>
  );
}
