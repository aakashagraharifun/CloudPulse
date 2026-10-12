"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/**
 * Theme context for components that call `useTheme()` (e.g. the landing hero).
 * CloudPulse is light-only for now (docs/design.md), so the theme is fixed to
 * light; dark sections opt in locally with a `.dark` wrapper.
 */
export function ThemeProvider(props: ComponentProps<typeof NextThemesProvider>) {
  return <NextThemesProvider {...props} />;
}
