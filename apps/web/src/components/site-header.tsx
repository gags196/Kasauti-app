import { cookies } from "next/headers";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { Link } from "@/i18n/navigation";
import { ELIMINATION_COOKIE, isEliminationEnabled } from "@/lib/elimination-mode";
import { getSessionToken } from "@/lib/session";
import { EliminationToggle } from "./elimination-toggle";
import { LocaleSwitch } from "./locale-switch";
import { SiteNav } from "./site-nav";

export async function SiteHeader() {
  const t = await getTranslations();
  const locale = await getLocale();
  // Read here rather than in the toggle: the mode has to be known on the server so a
  // question page can decide whether to fetch the lab at all.
  const labEnabled = isEliminationEnabled(
    (await cookies()).get(ELIMINATION_COOKIE)?.value,
  );
  // Presence of a session, not a fetch of it: the header renders on every page and must
  // not add an API round-trip to each one just to decide between two links.
  const signedIn = Boolean(await getSessionToken());

  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-baseline gap-x-6 gap-y-2 px-5 py-4">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          {t("brand.name")}
        </Link>
        <SiteNav
          items={[
            { href: "/pyq", label: t("nav.pyq") },
            { href: "/rankings", label: t("nav.rankings") },
            { href: "/trends", label: t("nav.trends") },
            { href: "/patterns", label: t("nav.patterns") },
            { href: "/elimination", label: t("lab.nav") },
            { href: "/practice", label: t("nav.practice") },
          ]}
        />
        <div className="ms-auto flex items-center gap-3">
          <Link
            href={signedIn ? "/me" : "/account/login"}
            className="text-sm text-ink-muted hover:text-ink"
          >
            {signedIn ? t("nav.me") : t("nav.signIn")}
          </Link>
          <EliminationToggle
            enabled={labEnabled}
            labelOn={t("lab.toggleOn")}
            labelOff={t("lab.toggleOff")}
          />
          {/* Reads the query string to preserve it across the switch, which
              opts this subtree out of static prerendering. */}
          <Suspense fallback={null}>
            <LocaleSwitch currentLocale={locale} label={t("nav.language")} />
          </Suspense>
        </div>
      </div>
    </header>
  );
}
