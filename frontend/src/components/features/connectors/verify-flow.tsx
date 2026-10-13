"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { useRef, useState } from "react";

import { FlowStage, StepList, type StepState } from "@/components/features/connectors/flow-stage";
import type { VerifyResponse } from "@/lib/api";

gsap.registerPlugin(useGSAP, MotionPathPlugin);

const REMOTE_CAPTION: Record<string, string> = {
  anthropic: "api.anthropic.com",
  openai: "api.openai.com",
  aws: "sts · ce · s3",
};

const PLACEHOLDER_STEPS: Record<string, string[]> = {
  anthropic: ["Authenticate the Admin API key", "Read the cost report"],
  openai: ["Authenticate the admin key", "Read organization costs"],
  aws: ["Authenticate with AWS STS", "Read billing data"],
};

/**
 * The real authorization check, animated: packets loop while the request is in
 * flight, then each step the backend reports is played back as a green (or red)
 * round trip. Remount (change `key`) for each new attempt.
 */
export function VerifyFlow({
  provider,
  phase,
  result,
  sandbox = false,
}: {
  provider: string;
  phase: "idle" | "verifying" | "done";
  result: VerifyResponse | null;
  /** A simulated account: shown with sandbox wording. */
  sandbox?: boolean;
}) {
  const scope = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(0);
  const [finished, setFinished] = useState(false);

  useGSAP(
    () => {
      const root = scope.current;
      const wire = root?.querySelector<SVGPathElement>("[data-flow=wire]");
      if (!root || !wire || phase === "idle") return;
      const q = gsap.utils.selector(root);
      const packets = q("[data-flow=packet]");
      const replies = q("[data-flow=reply]");
      const length = wire.getTotalLength();
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

      const travel = (target: Element, reverse: boolean, duration: number) => ({
        motionPath: {
          path: wire,
          align: wire,
          alignOrigin: [0.5, 0.5] as [number, number],
          start: reverse ? 1 : 0,
          end: reverse ? 0 : 1,
        },
        duration,
        ease: "power1.inOut",
        immediateRender: false,
        onStart: () => {
          gsap.set(target, { opacity: 1 });
        },
        onComplete: () => {
          gsap.set(target, { opacity: 0 });
        },
      });

      if (phase === "verifying") {
        if (reduce) {
          gsap.set(wire, { opacity: 0.6 });
          return;
        }
        // Waiting on the provider: the wire draws, then requests ping back and forth.
        gsap.set(wire, { strokeDasharray: length, strokeDashoffset: length, opacity: 1 });
        gsap.to(wire, { strokeDashoffset: 0, duration: 0.6, ease: "power2.out" });
        const loop = gsap.timeline({ repeat: -1, delay: 0.4 });
        loop.to(packets[0], travel(packets[0], false, 0.7)).to(replies[0], travel(replies[0], true, 0.7));
        return;
      }

      // phase === "done": play back what the backend reported.
      if (!result) return;
      const tl = gsap.timeline();
      gsap.set(wire, { strokeDasharray: "none", opacity: 1, stroke: "#3987e5" });
      result.steps.forEach((step, index) => {
        const reveal = () => setShown(index + 1);
        if (step.status === "skipped") {
          tl.call(reveal, [], "+=0.1");
          return;
        }
        if (reduce) {
          tl.call(reveal);
          return;
        }
        const packet = packets[index % packets.length];
        const reply = replies[index % replies.length];
        tl.to(packet, travel(packet, false, 0.55));
        if (step.status === "ok") {
          gsap.set(reply, { fill: "#1baf7a" });
          tl.to(reply, travel(reply, true, 0.55)).call(reveal);
        } else {
          tl.call(reveal)
            .to(q("[data-flow=remote]"), { x: -5, duration: 0.06, repeat: 5, yoyo: true, ease: "none" })
            .set(q("[data-flow=remote]"), { x: 0 });
        }
      });
      if (result.ok) {
        tl.to(wire, { stroke: "#1baf7a", duration: reduce ? 0 : 0.4 })
          .fromTo(
            q("[data-flow=badge-ok]"),
            { opacity: 0, scale: 0 },
            { opacity: 1, scale: 1, duration: reduce ? 0 : 0.4, ease: "back.out(3)" },
            "<",
          )
          .fromTo(q("[data-flow=identity]"), { opacity: 0 }, { opacity: 1, duration: reduce ? 0 : 0.3 }, "<");
      } else {
        tl.to(wire, { stroke: "#d03b3b", duration: reduce ? 0 : 0.3 }).fromTo(
          q("[data-flow=badge-fail]"),
          { opacity: 0, scale: 0 },
          { opacity: 1, scale: 1, duration: reduce ? 0 : 0.35, ease: "back.out(3)" },
          "<",
        );
      }
      tl.call(() => setFinished(true));
    },
    { scope, dependencies: [phase, result], revertOnUpdate: true },
  );

  const labels = result
    ? result.steps.map((s) => s.label)
    : sandbox
      ? ["Authorize the sandbox account", "Read billing data"]
      : (PLACEHOLDER_STEPS[provider] ?? PLACEHOLDER_STEPS.aws);
  const steps = labels.map((title, index) => {
    const reported = result?.steps[index];
    let state: StepState = "pending";
    let detail: string | undefined;
    if (reported && index < shown) {
      state = reported.status === "ok" ? "done" : reported.status === "failed" ? "failed" : "skipped";
      detail = reported.detail;
    } else if (phase !== "idle" && index === shown && !finished) {
      state = "active";
    }
    return { key: `${index}-${title}`, title, detail, state };
  });

  return (
    <div ref={scope} className="space-y-4">
      <FlowStage
        provider={provider}
        remoteCaption={sandbox ? "Sandbox" : (REMOTE_CAPTION[provider] ?? "")}
        identity={result?.identity}
      />
      <StepList steps={steps} />
      {phase === "idle" && (
        <p className="text-xs text-slate-500">
          {sandbox
            ? "Verifying opens a mock authorization window for a simulated account. No provider is contacted."
            : "Verifying makes read-only requests with the credentials you entered. Nothing is stored until you save."}
        </p>
      )}
      {phase === "verifying" && sandbox && (
        <p className="text-xs text-slate-500">Waiting for you to authorize in the pop-up window…</p>
      )}
    </div>
  );
}
