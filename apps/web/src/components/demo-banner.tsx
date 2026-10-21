import { getTranslations } from "next-intl/server";

/**
 * Visible whenever the database is loaded with seed_demo_questions.py fixtures.
 * Fabricated questions must never be mistakable for real past papers, so the
 * warning is site-wide rather than per-page.
 */
export async function DemoBanner() {
  if (process.env.NEXT_PUBLIC_DEMO_DATA !== "1") return null;
  const t = await getTranslations("demoBanner");

  return (
    <div className="bg-accent-soft px-5 py-2 text-center text-sm text-ink">
      <strong className="font-semibold">{t("title")}</strong> — {t("body")}
    </div>
  );
}
