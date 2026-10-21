"use client";

import { Link, usePathname } from "@/i18n/navigation";

/**
 * Highlighting needs the current route, which only exists on the client
 * (next-intl's usePathname strips the locale prefix so a bare route match
 * works under either language) — the rest of the header stays a server
 * component.
 */
export function SiteNav({
  items,
}: {
  items: { href: string; label: string }[];
}) {
  const pathname = usePathname();

  return (
    <nav className="flex gap-5 text-sm text-ink-muted">
      {items.map(({ href, label }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={
              active
                ? "font-semibold text-ink"
                : "hover:text-ink"
            }
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
