"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { RotateCcwIcon } from "lucide-react";
import { useRef, useState } from "react";

import { FlowStage, StepList, type StepState } from "@/components/features/connectors/flow-stage";
import { Badge, Button, Card } from "@/components/ui/primitives";

gsap.registerPlugin(useGSAP, MotionPathPlugin);

/**
 * A scripted, network-free walkthrough of what happens when an admin connects an
 * Anthropic organization. Every request shown is one the real connector makes
 * (app/services/connectors/anthropic_costs.py); the organization, key and
 * numbers are sample values.
 */

type Step = { key: string; title: string; detail: string; log: string[] };

const STEPS: Step[] = [
  {
    key: "seal",
    title: "Seal the Admin API key",
    detail: "Encrypted with Fernet before it is stored; the API never returns it.",
    log: [
      "• admin key received over HTTPS",
      "• Fernet encrypt (AES-128-CBC + HMAC-SHA256)",
      "• stored: gAAAAABnK3…  plaintext never hits the database",
    ],
  },
  {
    key: "authenticate",
    title: "Authenticate with Anthropic",
    detail: "GET /v1/organizations/me proves the key is an organization admin key.",
    log: [
      "→ GET https://api.anthropic.com/v1/organizations/me",
      "  x-api-key: sk-ant-admin01-••••••••3456",
      "  anthropic-version: 2023-06-01",
      '← 200 {"type":"organization","name":"Acme AI"}',
    ],
  },
  {
    key: "scope",
    title: "Check read access to cost data",
    detail: "A one-bucket cost report confirms the Usage & Cost Admin API is readable.",
    log: [
      "→ GET /v1/organizations/cost_report?starting_at=…&limit=1",
      "← 200 read access confirmed (read-only: nothing is ever written)",
    ],
  },
  {
    key: "pull",
    title: "Pull 30 days of daily costs",
    detail: "Grouped by workspace and description; amounts arrive in cents.",
    log: [
      "→ GET /v1/organizations/workspaces?include_archived=true",
      "→ GET /v1/organizations/cost_report?bucket_width=1d",
      "      &group_by[]=workspace_id&group_by[]=description&limit=31",
      "← 200 30 daily buckets · model · token_type · service_tier",
    ],
  },
  {
    key: "normalize",
    title: "Normalize, attribute and detect",
    detail: "Same validation, allocation rules and duplicate protection as a CSV upload.",
    log: [
      '✓ "123.78912" cents → $1.2378912 (exact decimals, no floats)',
      '✓ workspaces → projects: "Support assistant", "Default workspace"',
      "✓ anomaly detection and budget checks run on the new data",
    ],
  },
  {
    key: "connected",
    title: "Connected and scheduled",
    detail: "Re-syncs every 6 hours; restated days are replaced, never double-counted.",
    log: ["✓ connector saved · next sync in 6 h"],
  },
];

export function AnthropicPreview() {
  const scope = useRef<HTMLDivElement>(null);
  const [run, setRun] = useState(0);
  const [active, setActive] = useState(-1);
  const [playing, setPlaying] = useState(true);

  useGSAP(
    () => {
      const root = scope.current;
      if (!root) return;
      const q = gsap.utils.selector(root);
      const wire = root.querySelector<SVGPathElement>("[data-flow=wire]");
      if (!wire) return;
      const length = wire.getTotalLength();
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: reduce)", () => {
        // No motion: show the finished state.
        gsap.set(q("[data-flow=wire]"), { opacity: 1, stroke: "#1baf7a" });
        gsap.set(
          q(
            "[data-flow=lock], [data-flow=key], [data-flow=key-sealed], [data-flow=identity], [data-flow=badge-ok], [data-flow=counter]",
          ),
          { opacity: 1 },
        );
        gsap.set(q("[data-flow=key-plain]"), { opacity: 0 });
        gsap.set(q("[data-flow=pipe]"), { color: "#bbf7d0", borderColor: "rgba(74,222,128,0.5)" });
        q("[data-flow=count-buckets]")[0].textContent = "30";
        q("[data-flow=count-lines]")[0].textContent = "412";
        q("[data-flow=count-usd]")[0].textContent = "$1,284";
        gsap.delayedCall(0, () => {
          setActive(STEPS.length);
          setPlaying(false);
        });
      });

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const travel = (target: Element, reverse = false, duration = 0.9) => ({
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
        const packets = q("[data-flow=packet]");
        const replies = q("[data-flow=reply]");
        const remote = q("[data-flow=remote]");
        const local = q("[data-flow=local]");
        const step = (index: number) => () => setActive(index);

        gsap.set(wire, { strokeDasharray: length, strokeDashoffset: length, opacity: 1, stroke: "#3987e5" });

        for (const counter of q("[data-flow^=count-]")) counter.textContent = "0";
        const tl = gsap.timeline({ delay: 0.4, onComplete: () => setPlaying(false) });

        // 1. Seal the key: chip appears, encrypts, lock pops onto the CloudPulse node.
        tl.call(step(0))
          .fromTo(q("[data-flow=key]"), { opacity: 0, y: 8, scale: 0.9 }, { opacity: 1, y: 0, scale: 1, duration: 0.45, ease: "back.out(2)" })
          .to(q("[data-flow=key-plain]"), { opacity: 0, filter: "blur(4px)", duration: 0.4 }, "+=0.35")
          .fromTo(
            q("[data-flow=key-sealed]"),
            { opacity: 0, filter: "blur(4px)" },
            { opacity: 1, filter: "blur(0px)", duration: 0.4 },
            "<0.15",
          )
          .fromTo(q("[data-flow=lock]"), { opacity: 0, scale: 0 }, { opacity: 1, scale: 1, duration: 0.4, ease: "back.out(3)" }, "<")

          // 2. Authenticate: draw the wire, request out, identity back.
          .call(step(1), [], "+=0.3")
          .to(wire, { strokeDashoffset: 0, duration: 0.8, ease: "power2.inOut" })
          .to(packets[0], travel(packets[0]), "-=0.2")
          .to(remote, { scale: 1.06, duration: 0.15, yoyo: true, repeat: 1, ease: "power1.inOut" })
          .to(replies[0], travel(replies[0], true), "-=0.1")
          .fromTo(q("[data-flow=identity]"), { opacity: 0, y: -6 }, { opacity: 1, y: 0, duration: 0.35 }, "-=0.5")

          // 3. Scope check: a second round trip.
          .call(step(2), [], "+=0.25")
          .to(packets[1], travel(packets[1], false, 0.75))
          .to(replies[1], travel(replies[1], true, 0.75), "+=0.05")

          // 4. Pull: a stream of daily buckets with live counters.
          .call(step(3), [], "+=0.2")
          .to(packets[2], travel(packets[2], false, 0.6))
          .to(q("[data-flow=counter]"), { opacity: 1, duration: 0.3, stagger: 0.08 }, "<")
          .addLabel("stream");
        replies.slice(2).forEach((reply, i) => {
          tl.to(reply, travel(reply, true, 0.85), `stream+=${i * 0.16}`);
        });
        const counts = { buckets: 0, lines: 0, usd: 0 };
        tl.to(
          counts,
          {
            buckets: 30,
            lines: 412,
            usd: 1284,
            duration: 1.6,
            ease: "power1.out",
            onUpdate: () => {
              const [b, l, u] = [
                q("[data-flow=count-buckets]")[0],
                q("[data-flow=count-lines]")[0],
                q("[data-flow=count-usd]")[0],
              ];
              if (b) b.textContent = String(Math.round(counts.buckets));
              if (l) l.textContent = String(Math.round(counts.lines));
              if (u) u.textContent = `$${Math.round(counts.usd).toLocaleString("en-US")}`;
            },
          },
          "stream",
        )

          // 5. Normalize: the pipeline chips light up in order.
          .call(step(4), [], "+=0.1")
          .to(local, { scale: 1.05, duration: 0.2, yoyo: true, repeat: 1 })
          .to(q("[data-flow=pipe]"), { color: "#bbf7d0", borderColor: "rgba(74,222,128,0.5)", duration: 0.25, stagger: 0.3 }, "<")

          // 6. Connected: the wire turns green and the badge pops.
          .call(step(5), [], "+=0.3")
          .to(wire, { stroke: "#1baf7a", duration: 0.5 })
          .fromTo(q("[data-flow=badge-ok]"), { opacity: 0, scale: 0 }, { opacity: 1, scale: 1, duration: 0.45, ease: "back.out(3)" }, "<")
          .call(step(STEPS.length), [], "+=0.2");
      });

      return () => mm.revert();
    },
    { scope, dependencies: [run], revertOnUpdate: true },
  );

  function replay() {
    setActive(-1);
    setPlaying(true);
    setRun((value) => value + 1);
  }

  const states: StepState[] = STEPS.map((_, i) => (i < active ? "done" : i === active ? "active" : "pending"));
  const current = STEPS[Math.min(Math.max(active, 0), STEPS.length - 1)];
  const shownLogs = STEPS.slice(0, Math.max(0, Math.min(active + 1, STEPS.length)));

  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          How connecting Claude works
          <Badge tone="sample">Mock preview</Badge>
        </span>
      }
      description="A walkthrough of the authorization handshake with sample data. No network requests are made; the real flow runs when you verify your own Admin API key."
      action={
        <Button variant="secondary" size="sm" onClick={replay} disabled={playing}>
          <RotateCcwIcon className="size-3.5" aria-hidden />
          Replay
        </Button>
      }
    >
      <div ref={scope} className="space-y-5">
        <FlowStage
          provider="anthropic"
          remoteCaption="api.anthropic.com"
          localCaption="Acme AI workspace"
          identity="Acme AI · org admin"
          keyChip="sk-ant-admin01-••••3456"
          keySealed="gAAAAABnK3… sealed"
          pipeline={["Validate", "Allocate", "Detect"]}
          counters={[
            { key: "buckets", label: "Days" },
            { key: "lines", label: "Cost lines" },
            { key: "usd", label: "Spend" },
          ]}
        />
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <StepList
            steps={STEPS.map((s, i) => ({ key: s.key, title: s.title, detail: s.detail, state: states[i] }))}
          />
          <div
            className="min-h-48 overflow-hidden rounded-lg bg-ink-soft p-4 font-mono text-[11px] leading-relaxed text-slate-300 sm:text-xs"
            aria-label="Request log"
            aria-live="polite"
          >
            <p className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-500">
              <span className="size-1.5 rounded-full bg-good" aria-hidden />
              {active >= STEPS.length ? "complete" : current ? current.key : "ready"}
            </p>
            {shownLogs.map((s) => (
              <div key={s.key} className="mb-2 animate-appear motion-reduce:animate-none">
                {s.log.map((line, i) => (
                  <p
                    key={i}
                    className={
                      line.startsWith("←") || line.startsWith("✓")
                        ? "text-green-300 [overflow-wrap:anywhere] whitespace-pre-wrap"
                        : line.startsWith("→")
                          ? "text-brand-200 [overflow-wrap:anywhere] whitespace-pre-wrap"
                          : "[overflow-wrap:anywhere] whitespace-pre-wrap"
                    }
                  >
                    {line}
                  </p>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}
