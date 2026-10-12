import React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * A soft radial light placed behind content (e.g. a product screenshot).
 * Colours come from the `--brand` / `--brand-foreground` HSL tokens in globals.css.
 * Purely decorative: hidden from assistive technology and never intercepts clicks.
 */
const glowVariants = cva("pointer-events-none absolute w-full", {
  variants: {
    variant: {
      top: "top-0",
      above: "-top-[128px]",
      bottom: "bottom-0",
      below: "-bottom-[128px]",
      center: "top-[50%]",
    },
  },
  defaultVariants: {
    variant: "top",
  },
});

export interface GlowProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof glowVariants> {}

const Glow = React.forwardRef<HTMLDivElement, GlowProps>(
  ({ className, variant, ...props }, ref) => (
    <div
      ref={ref}
      aria-hidden
      className={cn(glowVariants({ variant }), className)}
      {...props}
    >
      <div
        className={cn(
          "absolute left-1/2 h-[256px] w-[60%] -translate-x-1/2 scale-[2.5] rounded-[50%] bg-[radial-gradient(ellipse_at_center,hsl(var(--brand-foreground)/0.5)_10%,hsl(var(--brand-foreground)/0)_60%)] sm:h-[512px]",
          variant === "center" && "-translate-y-1/2",
        )}
      />
      <div
        className={cn(
          "absolute left-1/2 h-[128px] w-[40%] -translate-x-1/2 scale-[2] rounded-[50%] bg-[radial-gradient(ellipse_at_center,hsl(var(--brand)/0.3)_10%,hsl(var(--brand-foreground)/0)_60%)] sm:h-[256px]",
          variant === "center" && "-translate-y-1/2",
        )}
      />
    </div>
  ),
);
Glow.displayName = "Glow";

export { Glow };
