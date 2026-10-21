"use client";

import { useSearchParams } from "next/navigation";

import { Link, usePathname } from "@/i18n/navigation";
import type { Locale } from "@/i18n/routing";

/**
 * Switches locale in place: same route, same query, other language. Losing the
 * user's position on language change is the fastest way to make a bilingual
 * product feel like two separate sites.
 */
export function LocaleSwitch({
  currentLocale,
  label,
}: {
  currentLocale: string;
  label: string;
}) {
  // next-intl's usePathname returns the route without the locale prefix, so
  // the same value re-resolves correctly under the target locale.
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const target: Locale = currentLocale === "hi" ? "en" : "hi";
  const query = Object.fromEntries(searchParams.entries());

  return (
    <Link
      href={{ pathname, query }}
      locale={target}
      className="rounded-full border border-rule px-3 py-1 text-sm text-ink-muted hover:border-ink hover:text-ink"
    >
      {label}
    </Link>
  );
}
