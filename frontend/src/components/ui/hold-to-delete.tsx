"use client";

import gsap from "gsap";
import { Trash2Icon } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { buttonClass, cx } from "@/components/ui/primitives";

const HOLD_SECONDS = 3;

type Phase = "idle" | "holding" | "working";

/**
 * A destructive action that only fires after the button is held for three
 * seconds (mouse, touch, or Space/Enter). A red fill sweeps across while
 * holding; letting go early rewinds it and nothing happens. Replaces
 * confirmation dialogs, which are easy to click through by reflex.
 */
export function HoldToDeleteButton({
  onConfirm,
  label,
  consequence,
  disabled = false,
  className,
}: {
  onConfirm: () => void | Promise<void>;
  /** What is deleted, for screen readers, e.g. `budget "Monthly cloud"`. */
  label: string;
  /** What deleting means, shown as a tooltip and read by screen readers. */
  consequence?: string;
  disabled?: boolean;
  className?: string;
}) {
  const scope = useRef<HTMLButtonElement>(null);
  const fill = useRef<HTMLSpanElement>(null);
  const tween = useRef<gsap.core.Tween | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [remaining, setRemaining] = useState(HOLD_SECONDS);
  const consequenceId = useId();

  // Tweens start from event handlers, so stop them ourselves on unmount.
  useEffect(() => () => void tween.current?.kill(), []);

  function start() {
    if (disabled || phase !== "idle" || !fill.current) return;
    setPhase("holding");
    setRemaining(HOLD_SECONDS);
    tween.current?.kill();
    tween.current = gsap.fromTo(
      fill.current,
      { scaleX: 0 },
      {
        scaleX: 1,
        duration: HOLD_SECONDS,
        ease: "none",
        onUpdate() {
          const left = Math.max(1, Math.ceil(HOLD_SECONDS * (1 - this.progress())));
          setRemaining((current) => (current === left ? current : left));
        },
        onComplete: () => {
          setPhase("working");
          void Promise.resolve(onConfirm()).finally(() => {
            // The row usually disappears; if it doesn't (e.g. an error), reset.
            if (!scope.current?.isConnected) return;
            gsap.set(fill.current, { scaleX: 0 });
            setPhase("idle");
          });
        },
      },
    );
  }

  function cancel() {
    if (phase !== "holding" || !fill.current) return;
    tween.current?.kill();
    tween.current = gsap.to(fill.current, { scaleX: 0, duration: 0.25, ease: "power2.out" });
    setPhase("idle");
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if ((event.key === " " || event.key === "Enter") && !event.repeat) {
      event.preventDefault();
      start();
    }
  }

  function onKeyUp(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      cancel();
    }
  }

  const text =
    phase === "holding" ? `Keep holding… ${remaining}s` : phase === "working" ? "Deleting…" : "Hold to delete";

  return (
    <button
      ref={scope}
      type="button"
      disabled={disabled || phase === "working"}
      title={consequence ? `${consequence} Hold for ${HOLD_SECONDS} seconds to delete.` : undefined}
      aria-label={`Hold for ${HOLD_SECONDS} seconds to delete ${label}`}
      aria-describedby={consequence ? consequenceId : undefined}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        start();
      }}
      onPointerUp={cancel}
      onPointerCancel={cancel}
      onLostPointerCapture={cancel}
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
      onBlur={cancel}
      onContextMenu={(event) => event.preventDefault()}
      className={cx(
        buttonClass("danger", "sm"),
        // Fixed width so the label change while holding never reflows the row.
        "relative min-w-36 touch-none select-none overflow-hidden whitespace-nowrap",
        phase === "holding" && "text-red-800",
        className,
      )}
    >
      <span
        ref={fill}
        aria-hidden
        className="absolute inset-0 origin-left bg-red-200"
        // Inline transform (not Tailwind's scale-x-0, which sets the separate `scale`
        // property and would multiply with GSAP's transform).
        style={{ transform: "scaleX(0)" }}
      />
      {consequence && (
        <span id={consequenceId} className="sr-only">
          {consequence}
        </span>
      )}
      <span className="relative inline-flex items-center gap-1.5 tabular-nums" aria-live="polite">
        <Trash2Icon className="size-3.5" aria-hidden />
        {text}
      </span>
    </button>
  );
}
