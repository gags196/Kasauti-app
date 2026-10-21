"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ELIMINATION_COOKIE } from "@/lib/elimination-mode";

/**
 * Turns Elimination Lab mode on and off, incognito-style: a mode the reader opts into,
 * which then changes what every question page shows.
 *
 * State lives in a **cookie**, not localStorage, so the server component decides. With
 * localStorage the page would have to render the lab into the DOM and hide it, which
 * means fetching and shipping an analysis for a reader who has the mode switched off.
 * A cookie means the mode is simply not there when it is off.
 *
 * This is the second client component in the app, after the locale switch. It earns that
 * because the toggle has to write a cookie from the browser and refresh the tree.
 *
 * The cookie name comes from `lib/elimination-mode` rather than being declared here, so
 * the server can read the same constant — see that file for why it cannot live in a
 * `"use client"` module.
 */

export function EliminationToggle({
  enabled,
  labelOn,
  labelOff,
}: {
  enabled: boolean;
  labelOn: string;
  labelOff: string;
}) {
  const router = useRouter();
  // The server already rendered with `enabled`; track it locally so the button label
  // flips on click rather than after the refresh round-trip.
  const [on, setOn] = useState(enabled);
  useEffect(() => setOn(enabled), [enabled]);

  function toggle() {
    const next = !on;
    setOn(next);
    // A year, path-wide. Nothing here identifies a reader, so there is nothing to expire
    // sooner for privacy's sake — it is a display preference.
    document.cookie = next
      ? `${ELIMINATION_COOKIE}=1; path=/; max-age=31536000; samesite=lax`
      : `${ELIMINATION_COOKIE}=; path=/; max-age=0; samesite=lax`;
    router.refresh();
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={on}
      className={`rounded-full border px-3 py-1 text-sm transition-colors ${
        on
          ? "border-accent bg-accent-soft text-accent"
          : "border-rule text-ink-muted hover:border-ink hover:text-ink"
      }`}
    >
      {on ? labelOn : labelOff}
    </button>
  );
}
