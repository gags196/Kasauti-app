import { getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { Link, redirect } from "@/i18n/navigation";
import { ApiError, api, type StartOptions } from "@/lib/api";
import { getSessionToken } from "@/lib/session";

import { startPractice } from "./actions";

/**
 * Choose a paper to sit.
 *
 * Three modes, and the difference between them is stated rather than implied: a real
 * year paper produces a score comparable to what other people scored on that paper, and
 * the two constructed modes do not. Only years with a complete keyed paper behind them
 * are offered — the corpus decides what is sittable, not a hardcoded list.
 *
 * A paper is chosen before a year, because two papers now share years and a sitting is
 * one printed booklet. Paper II is labelled as qualifying where it is offered: its score
 * does not enter the merit list, and a learner deciding how to spend two hours should
 * know that before they start rather than after.
 */
export default async function PracticePage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("practice");
  const { error } = await searchParams;

  if (!(await getSessionToken())) redirect({ href: "/account/login", locale });

  let options: StartOptions;
  try {
    options = await api.practiceOptions();
  } catch (caught) {
    if (caught instanceof ApiError) return <ApiErrorNotice error={caught} />;
    throw caught;
  }

  const minutes = Math.round(options.full_mock_seconds / 60);
  // Papers with at least one complete keyed year behind them; the API decides.
  const papers = options.papers;
  const defaultPaper = papers[0];

  return (
    <article>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-2 max-w-2xl text-ink-muted">{t("lede")}</p>

      {error === "not-enough" ? (
        <p role="alert" className="mt-4 rounded-lg border border-caution p-4 text-sm">
          {t("notEnough")}
        </p>
      ) : null}

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <section className="rounded-lg border border-rule bg-paper-raised p-5">
          <h2 className="font-medium">{t("yearTitle")}</h2>
          <p className="mt-1 text-sm text-ink-muted">{t("yearBody")}</p>
          {papers.length === 0 ? (
            <p className="mt-4 text-sm text-ink-muted">{t("noPapers")}</p>
          ) : (
            papers.map((paper) => (
            <form
              key={paper.code}
              action={startPractice}
              className="mt-4 flex flex-wrap items-end gap-3"
            >
              <input type="hidden" name="mode" value="year_paper" />
              <input type="hidden" name="paper_code" value={paper.code} />
              <label className="grid gap-1.5 text-sm">
                <span className="text-ink-muted">
                  {locale === "hi" ? paper.name_hi : paper.name_en}
                  {paper.qualifying ? ` — ${t("qualifyingPaper")}` : ""}
                </span>
                <select
                  name="year"
                  defaultValue={paper.years[0]}
                  className="rounded-lg border border-rule bg-paper-raised px-3 py-2"
                >
                  {paper.years.map((year) => (
                    <option key={year} value={year}>
                      {year}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="submit"
                className="rounded-full border border-accent bg-accent-soft px-4 py-2 text-sm text-accent"
              >
                {t("start")}
              </button>
            </form>
            ))
          )}
        </section>

        <section className="rounded-lg border border-rule bg-paper-raised p-5">
          <h2 className="font-medium">{t("mockTitle")}</h2>
          <p className="mt-1 text-sm text-ink-muted">
            {t("mockBody", { count: options.full_mock_questions, minutes })}
          </p>
          <form action={startPractice} className="mt-4 flex flex-wrap items-end gap-3">
            <input type="hidden" name="mode" value="full_mock" />
            {/* A mock is drawn from one paper's corpus, never a blend of two. */}
            <input type="hidden" name="paper_code" value={defaultPaper?.code ?? ""} />
            <label className="grid gap-1.5 text-sm">
              <span className="text-ink-muted">{t("countLabel")}</span>
              <select
                name="count"
                defaultValue={options.full_mock_questions}
                className="rounded-lg border border-rule bg-paper-raised px-3 py-2"
              >
                {[10, 25, 50, options.full_mock_questions].map((count) => (
                  <option key={count} value={count}>
                    {count}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              className="rounded-full border border-accent bg-accent-soft px-4 py-2 text-sm text-accent"
            >
              {t("start")}
            </button>
          </form>
        </section>
      </div>

      <section className="mt-6 rounded-lg border border-rule bg-paper-raised p-5">
        <h2 className="font-medium">{t("drillTitle")}</h2>
        <p className="mt-1 text-sm text-ink-muted">{t("drillBody")}</p>
        <form action={startPractice} className="mt-4 flex flex-wrap items-end gap-3">
          <input type="hidden" name="mode" value="topic_drill" />
          <label className="grid gap-1.5 text-sm">
            <span className="text-ink-muted">{t("topicLabel")}</span>
            <input
              name="topic_path"
              required
              placeholder="gs3.indian_economy"
              className="w-64 rounded-lg border border-rule bg-paper-raised px-3 py-2 font-mono text-sm"
            />
          </label>
          <label className="grid gap-1.5 text-sm">
            <span className="text-ink-muted">{t("countLabel")}</span>
            <select
              name="count"
              defaultValue={options.drill_default_questions}
              className="rounded-lg border border-rule bg-paper-raised px-3 py-2"
            >
              {[10, 20, 30].map((count) => (
                <option key={count} value={count}>
                  {count}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="rounded-full border border-accent bg-accent-soft px-4 py-2 text-sm text-accent"
          >
            {t("start")}
          </button>
        </form>
        <p className="mt-3 text-xs text-ink-muted">
          {t("drillHint")}{" "}
          <Link href="/rankings" className="text-accent hover:underline">
            {t("drillHintLink")}
          </Link>
        </p>
      </section>

      <p className="mt-8 max-w-2xl text-sm text-ink-muted">{t("footnote")}</p>
    </article>
  );
}
