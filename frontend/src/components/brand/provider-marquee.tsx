import type { LucideIcon } from "lucide-react";
import { BrainCircuitIcon, CloudIcon } from "lucide-react";

import { BRAND_ICONS, type BrandIconKey } from "@/components/brand/brand-icons";
import { cn } from "@/lib/utils";

type Provider = { name: string } & ({ brand: BrandIconKey } | { icon: LucideIcon });

// Providers whose exports CloudPulse recognises by name (backend: app/services/providers.py).
// Marks without a Simple Icons entry are shown by name with a neutral icon, never a lookalike logo.
const PROVIDERS: Provider[] = [
  { name: "AWS", icon: CloudIcon },
  { name: "Google Cloud", brand: "googlecloud" },
  { name: "Microsoft Azure", icon: CloudIcon },
  { name: "OpenAI", icon: BrainCircuitIcon },
  { name: "Anthropic", brand: "anthropic" },
  { name: "Google Gemini", brand: "googlegemini" },
  { name: "Mistral AI", brand: "mistralai" },
  { name: "DeepSeek", brand: "deepseek" },
  { name: "Hugging Face", brand: "huggingface" },
  { name: "Oracle Cloud", icon: CloudIcon },
  { name: "Alibaba Cloud", brand: "alibabacloud" },
  { name: "DigitalOcean", brand: "digitalocean" },
  { name: "Cloudflare", brand: "cloudflare" },
  { name: "Datadog", brand: "datadog" },
  { name: "Snowflake", brand: "snowflake" },
  { name: "Databricks", brand: "databricks" },
  { name: "MongoDB Atlas", brand: "mongodb" },
];

function ProviderList({ duplicate = false }: { duplicate?: boolean }) {
  return (
    <ul
      // The second copy only exists to make the loop seamless.
      aria-hidden={duplicate || undefined}
      className={cn(
        "flex shrink-0 items-center gap-x-12 pr-12",
        duplicate && "motion-reduce:hidden",
        "motion-reduce:w-full motion-reduce:shrink motion-reduce:flex-wrap motion-reduce:justify-center motion-reduce:gap-y-6 motion-reduce:pr-0",
      )}
    >
      {PROVIDERS.map((provider) => (
        <li key={provider.name} className="flex shrink-0 items-center gap-2.5 text-muted-foreground">
          {"brand" in provider ? (
            <svg viewBox="0 0 24 24" className="size-6" fill="currentColor" aria-hidden focusable="false">
              <path d={BRAND_ICONS[provider.brand].path} />
            </svg>
          ) : (
            <provider.icon className="size-6" strokeWidth={1.75} aria-hidden />
          )}
          <span className="whitespace-nowrap text-base font-semibold tracking-tight">{provider.name}</span>
        </li>
      ))}
    </ul>
  );
}

/** Continuously scrolling strip of provider names; static and wrapped when reduced motion is preferred. */
export function ProviderMarquee({ className }: { className?: string }) {
  return (
    <section aria-labelledby="providers-heading" className={cn("bg-background pb-4 pt-12 text-foreground sm:pt-16", className)}>
      <div className="mx-auto max-w-container px-4">
        <h2 id="providers-heading" className="text-center text-sm font-medium text-muted-foreground">
          Bring cost data from every provider you pay: cloud, AI model APIs and SaaS
        </h2>
        <div className="fade-x group mt-8 overflow-hidden motion-reduce:[mask-image:none]">
          <div className="flex w-max animate-marquee-right group-hover:[animation-play-state:paused] motion-reduce:w-full motion-reduce:animate-none">
            <ProviderList />
            <ProviderList duplicate />
          </div>
        </div>
        <p className="mt-8 text-center text-xs text-muted-foreground">
          Imported from billing CSV exports. Names and marks belong to their owners and do not imply endorsement.
        </p>
      </div>
    </section>
  );
}
