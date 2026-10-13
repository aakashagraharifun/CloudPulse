"use client";

import { BrainCircuitIcon, CheckIcon, CloudIcon, LockIcon, XIcon } from "lucide-react";
import { useId, type ReactNode } from "react";

import { BRAND_ICONS } from "@/components/brand/brand-icons";
import { LogoMark } from "@/components/brand/logo";
import { cx } from "@/components/ui/primitives";

/**
 * The CloudPulse ⇄ provider "wire" that connection flows animate with GSAP.
 *
 * Purely presentational: animated parts carry `data-flow` attributes and the
 * owning component targets them inside its own scope, so several stages can be
 * on one page. SVG and HTML layers share one coordinate space (VIEW_W x VIEW_H)
 * because the container keeps the same aspect ratio.
 */

export const VIEW_W = 640;
export const VIEW_H = 220;
const NODE = { w: 168, h: 92, y: 58 };
const LOCAL_X = 20;
const REMOTE_X = VIEW_W - 20 - NODE.w;
const WIRE_Y = NODE.y + NODE.h / 2;
export const WIRE_PATH = `M${LOCAL_X + NODE.w} ${WIRE_Y} C ${LOCAL_X + NODE.w + 90} ${WIRE_Y - 70}, ${
  REMOTE_X - 90
} ${WIRE_Y + 70}, ${REMOTE_X} ${WIRE_Y}`;
export const PACKETS = 3;
export const REPLIES = 8;

const pct = (value: number, of: number) => `${(value / of) * 100}%`;

/** Provider marks: Simple Icons where one exists, otherwise a neutral icon (see brand-icons.ts). */
export function ProviderMark({ provider, className }: { provider: string; className?: string }) {
  if (provider === "anthropic") {
    return (
      <svg viewBox="0 0 24 24" className={cx("size-6", className)} fill="currentColor" aria-hidden>
        <path d={BRAND_ICONS.anthropic.path} />
      </svg>
    );
  }
  const Icon = provider === "openai" ? BrainCircuitIcon : CloudIcon;
  return <Icon className={cx("size-6", className)} strokeWidth={1.75} aria-hidden />;
}

export const PROVIDER_LABEL: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  aws: "AWS",
};

function Node({
  x,
  flow,
  children,
}: {
  x: number;
  flow: "local" | "remote";
  children: ReactNode;
}) {
  return (
    <div
      data-flow={flow}
      className="absolute flex flex-col items-center justify-center gap-1.5 rounded-2xl border border-white/15 bg-white/[0.06] text-center shadow-[0_0_0_1px_rgba(255,255,255,0.02),0_20px_40px_-20px_rgba(0,0,0,0.6)] backdrop-blur-sm"
      style={{
        left: pct(x, VIEW_W),
        top: pct(NODE.y, VIEW_H),
        width: pct(NODE.w, VIEW_W),
        height: pct(NODE.h, VIEW_H),
      }}
    >
      {children}
    </div>
  );
}

export function FlowStage({
  provider,
  remoteCaption,
  localCaption = "Your workspace",
  identity,
  keyChip,
  keySealed,
  pipeline,
  counters,
  className,
}: {
  provider: string;
  remoteCaption: string;
  localCaption?: string;
  /** Text of the identity pill under the provider node (revealed by the animation). */
  identity?: string | null;
  /** Text of the credential chip under the CloudPulse node (revealed by the animation). */
  keyChip?: string;
  /** What the credential chip shows once sealed (crossfaded in by the animation). */
  keySealed?: string;
  /** Labels of the pipeline chips under the CloudPulse node. */
  pipeline?: string[];
  /** Labels of the live counters above the wire. */
  counters?: { key: string; label: string }[];
  className?: string;
}) {
  // Unique per stage so two stages on a page never share a filter id.
  const glow = `flow-glow-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return (
    <div
      className={cx(
        "relative w-full select-none overflow-hidden rounded-xl bg-ink text-white",
        "bg-[radial-gradient(circle_at_1px_1px,rgba(255,255,255,0.07)_1px,transparent_0)] [background-size:18px_18px]",
        className,
      )}
    >
      <div className="relative w-full" style={{ aspectRatio: `${VIEW_W} / ${VIEW_H}` }}>
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          className="absolute inset-0 size-full"
          aria-hidden
          focusable="false"
        >
          <defs>
            <filter id={glow} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="3.5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          <path d={WIRE_PATH} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="2" strokeDasharray="4 6" />
          <path
            data-flow="wire"
            d={WIRE_PATH}
            fill="none"
            stroke="#3987e5"
            strokeWidth="2.5"
            strokeLinecap="round"
            filter={`url(#${glow})`}
            opacity="0"
          />
          {Array.from({ length: PACKETS }, (_, i) => (
            <circle key={`p${i}`} data-flow="packet" r="5.5" fill="#9ec5f4" filter={`url(#${glow})`} opacity="0" />
          ))}
          {Array.from({ length: REPLIES }, (_, i) => (
            <circle key={`r${i}`} data-flow="reply" r="4.5" fill="#1baf7a" filter={`url(#${glow})`} opacity="0" />
          ))}
        </svg>

        <Node x={LOCAL_X} flow="local">
          <LogoMark className="size-7 sm:size-9" />
          <span className="hidden text-xs font-semibold sm:block">CloudPulse</span>
          <span className="hidden text-[10px] text-white/50 md:block">{localCaption}</span>
          <span
            data-flow="lock"
            className="absolute -right-2 -top-2 flex size-6 items-center justify-center rounded-full bg-good text-white opacity-0 ring-4 ring-ink"
          >
            <LockIcon className="size-3" strokeWidth={2.5} />
          </span>
        </Node>

        <Node x={REMOTE_X} flow="remote">
          <ProviderMark provider={provider} className="size-7 text-white sm:size-9" />
          <span className="hidden text-xs font-semibold sm:block">{PROVIDER_LABEL[provider] ?? provider}</span>
          <span className="hidden text-[10px] text-white/50 md:block">{remoteCaption}</span>
        </Node>

        {/* Outcome badge in the middle of the wire. */}
        <span
          data-flow="badge-ok"
          className="absolute flex size-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-good text-white opacity-0 shadow-[0_0_24px_rgba(12,163,12,0.6)]"
          style={{ left: "50%", top: pct(WIRE_Y, VIEW_H) }}
        >
          <CheckIcon className="size-4" strokeWidth={3} />
        </span>
        <span
          data-flow="badge-fail"
          className="absolute flex size-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-critical text-white opacity-0 shadow-[0_0_24px_rgba(208,59,59,0.6)]"
          style={{ left: "50%", top: pct(WIRE_Y, VIEW_H) }}
        >
          <XIcon className="size-4" strokeWidth={3} />
        </span>

        {counters && (
          <div className="absolute inset-x-0 top-[6%] hidden justify-center gap-6 sm:flex">
            {counters.map((counter) => (
              <div key={counter.key} data-flow="counter" className="text-center opacity-0">
                <div data-flow={`count-${counter.key}`} className="font-mono text-sm font-semibold tabular-nums sm:text-lg">
                  0
                </div>
                <div className="text-[10px] uppercase tracking-wider text-white/50">{counter.label}</div>
              </div>
            ))}
          </div>
        )}

        {keyChip && (
          <span
            data-flow="key"
            className="absolute hidden -translate-x-1/2 whitespace-nowrap sm:grid rounded-md border border-white/15 bg-white/10 px-2 py-0.5 font-mono text-[9px] text-white/80 opacity-0 sm:text-[11px]"
            style={{ left: pct(LOCAL_X + NODE.w / 2, VIEW_W), top: pct(NODE.y + NODE.h + 12, VIEW_H) }}
          >
            <span data-flow="key-plain" className="[grid-area:1/1]">
              {keyChip}
            </span>
            {keySealed && (
              <span data-flow="key-sealed" className="text-green-300 opacity-0 [grid-area:1/1]">
                {keySealed}
              </span>
            )}
          </span>
        )}

        {pipeline && (
          <div
            className="absolute hidden -translate-x-1/2 gap-1 sm:flex"
            style={{ left: pct(LOCAL_X + NODE.w / 2, VIEW_W), top: pct(NODE.y - 30, VIEW_H) }}
          >
            {pipeline.map((label) => (
              <span
                key={label}
                data-flow="pipe"
                className="whitespace-nowrap rounded-full border border-white/15 px-1.5 py-0.5 text-[9px] font-medium text-white/40 sm:px-2 sm:text-[10px]"
              >
                {label}
              </span>
            ))}
          </div>
        )}

        <span
          data-flow="identity"
          className="absolute hidden max-w-[40%] -translate-x-1/2 truncate sm:block whitespace-nowrap rounded-full bg-good/20 px-2.5 py-0.5 text-[9px] font-medium text-green-200 opacity-0 ring-1 ring-inset ring-green-400/30 sm:text-[11px]"
          style={{ left: pct(REMOTE_X + NODE.w / 2, VIEW_W), top: pct(NODE.y + NODE.h + 12, VIEW_H) }}
        >
          {identity ?? ""}
        </span>
      </div>
    </div>
  );
}

// --- step list -------------------------------------------------------------------

export type StepState = "pending" | "active" | "done" | "failed" | "skipped";

export function StepList({
  steps,
}: {
  steps: { key: string; title: string; detail?: ReactNode; state: StepState }[];
}) {
  return (
    <ol className="space-y-3">
      {steps.map((step, index) => (
        <li key={step.key} className="flex gap-3">
          <span
            aria-hidden
            className={cx(
              "relative mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold transition-colors duration-300",
              step.state === "done" && "bg-good text-white",
              step.state === "failed" && "bg-critical text-white",
              step.state === "active" && "bg-brand-600 text-white",
              step.state === "pending" && "bg-slate-100 text-slate-500",
              step.state === "skipped" && "bg-slate-100 text-slate-400",
            )}
          >
            {step.state === "active" && (
              <span className="absolute inset-0 animate-ping rounded-full bg-brand-500/40 motion-reduce:hidden" />
            )}
            {step.state === "done" ? (
              <CheckIcon className="size-3.5" strokeWidth={3} />
            ) : step.state === "failed" ? (
              <XIcon className="size-3.5" strokeWidth={3} />
            ) : (
              index + 1
            )}
          </span>
          <div className="min-w-0">
            <p
              className={cx(
                "text-sm font-medium transition-colors duration-300",
                step.state === "pending" || step.state === "skipped" ? "text-slate-500" : "text-slate-900",
              )}
            >
              {step.title}
              <span className="sr-only">
                {" "}
                ({step.state === "done" ? "complete" : step.state === "active" ? "in progress" : step.state})
              </span>
            </p>
            {step.detail && (
              <p
                className={cx(
                  "mt-0.5 text-xs [overflow-wrap:anywhere]",
                  step.state === "failed" ? "text-red-700" : "text-slate-500",
                )}
              >
                {step.detail}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
