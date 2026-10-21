import { getTranslations, setRequestLocale } from "next-intl/server";

import { Link } from "@/i18n/navigation";

export default async function HomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations();

  const cards = [
    { href: "/pyq", title: t("home.cards.pyqTitle"), body: t("home.cards.pyqBody") },
    {
      href: "/rankings",
      title: t("home.cards.rankingsTitle"),
      body: t("home.cards.rankingsBody"),
    },
    {
      href: "/rankings",
      title: t("home.cards.analysisTitle"),
      body: t("home.cards.analysisBody"),
    },
    {
      href: "/trends",
      title: t("home.cards.trendsTitle"),
      body: t("home.cards.trendsBody"),
    },
    {
      href: "/patterns",
      title: t("home.cards.patternsTitle"),
      body: t("home.cards.patternsBody"),
    },
    {
      href: "/elimination",
      title: t("home.cards.labTitle"),
      body: t("home.cards.labBody"),
    },
  ];

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">{t("brand.tagline")}</h1>
      <p className="mt-4 max-w-2xl text-lg text-ink-muted">{t("home.lede")}</p>

      {/* The strongest thing this product can say, said first. Every competitor claims
          to teach elimination tricks; this is the only one that tested them and
          published the result — including that almost all of them fail. Burying that
          under a feature grid was the cheapest fixable mistake in the app. */}
      <Link
        href="/elimination"
        className="mt-8 block rounded-lg border border-accent/50 bg-accent-soft/40 p-6 transition-colors hover:border-accent"
      >
        <p className="text-sm font-medium text-accent">{t("home.hero.kicker")}</p>
        <p className="mt-2 text-xl leading-snug">{t("home.hero.claim")}</p>
        <p className="mt-3 max-w-2xl text-sm text-ink-muted">{t("home.hero.body")}</p>
        <p className="mt-3 text-sm text-accent">{t("home.hero.cta")} →</p>
      </Link>

      <div className="mt-10 grid gap-4 sm:grid-cols-2">
        {cards.map((card) => (
          <Link
            key={card.title}
            href={card.href}
            className="rounded-lg border border-rule bg-paper-raised p-5 transition-colors hover:border-ink"
          >
            <h2 className="font-medium">{card.title}</h2>
            <p className="mt-2 text-sm text-ink-muted">{card.body}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
