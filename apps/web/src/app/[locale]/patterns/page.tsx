import { getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { Legend, StackedBar, bucketLabel } from "@/components/bars";
import { Link } from "@/i18n/navigation";
import { ApiError, api, type Era, type Patterns, type Recurrence } from "@/lib/api";

/**
 * The founder's fourth question, measured: *is there a pattern UPSC follows on hard
 * questions?* — same letter as the answer, odd-one-out, the unfamiliar-three tell,
 * dated options.
 *
 * Every one of them comes back **not a usable signal**, and that is what this page is
 * for. These are the beliefs an aspirant spends time on, and the corpus can settle them
 * in a way no coaching video can. Two framings are load-bearing:
 *
 * - **The baseline is not 25%.** In half the corpus the options are "1 only / 2 only /
 *   Both 1 and 2 / Neither 1 nor 2", where "Both 1 and 2" is mechanically the longest
 *   string. Rates are compared against a null built by permuting which option is correct
 *   *within each archetype*.
 * - **Five hypotheses means a corrected threshold**, or one of them fires by construction.
 *
 * The recurrence curve sits below because it is the one thing on this page that *is*
 * actionable: questions genuinely do repeat, unevenly, and the per-topic rate is where
 * that shows.
 */
const ERAS: { key: Era; labelKey: "eraRecent" | "eraAll" | "eraLegacy" }[] = [
  { key: "recent", labelKey: "eraRecent" },
  { key: "all", labelKey: "eraAll" },
  { key: "legacy", labelKey: "eraLegacy" },
];

export default async function PatternsPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ era?: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("patterns");
  const { era: raw } = await searchParams;
  const era: Era = ERAS.find((e) => e.key === raw)?.key ?? "recent";

  let data: Patterns;
  let recurrence: Recurrence;
  try {
    // Recurrence is text/embedding-based and does run on Mains, but this page reads it
    // beside option-construction analysis that cannot. Left unscoped it pairs a Prelims
    // MCQ against a Mains essay prompt in the same topic and calls that a repeat.
    [data, recurrence] = await Promise.all([
      api.patterns(era),
      api.recurrence({ stage: "prelims" }),
    ]);
  } catch (error) {
    if (error instanceof ApiError) return <ApiErrorNotice error={error} />;
    throw error;
  }

  const usable = data.hypotheses.filter(
    (h) => h.verdict === "signal" || h.verdict === "inverse_signal",
  );
  const archetypeTotal =
    Object.values(data.archetype_mix).reduce((sum, n) => sum + n, 0) || 1;
  const archetypes = Object.entries(data.archetype_mix);
  const letters = Object.entries(data.label_distribution);
  const letterTotal = letters.reduce((sum, [, n]) => sum + n, 0) || 1;

  return (
    <article>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-2 max-w-2xl text-ink-muted">{t("lede")}</p>

      <nav className="mt-6 flex flex-wrap gap-2">
        {ERAS.map((option) => (
          <Link
            key={option.key}
            href={{ pathname: "/patterns", query: { era: option.key } }}
            className={`rounded-full border px-3 py-1 text-sm ${
              option.key === era
                ? "border-accent bg-accent-soft text-accent"
                : "border-rule text-ink-muted hover:border-ink hover:text-ink"
            }`}
          >
            {t(option.labelKey)}
          </Link>
        ))}
      </nav>

      <p className="mt-6 text-sm text-ink-muted">
        {t("scopeline", {
          n: data.keyed_questions,
          from: data.year_from ?? 0,
          to: data.year_to ?? 0,
          usable: usable.length,
          total: data.hypotheses.length,
        })}
      </p>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[42rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-ink-muted">
              <th className="py-2 pe-4 text-start font-medium">{t("colBelief")}</th>
              <th className="py-2 pe-4 text-end font-medium">{t("colN")}</th>
              <th className="py-2 pe-4 text-end font-medium">{t("colRate")}</th>
              <th className="py-2 pe-4 text-end font-medium">{t("colBaseline")}</th>
              <th className="py-2 text-start font-medium">{t("colVerdict")}</th>
            </tr>
          </thead>
          <tbody>
            {data.hypotheses.map((hypothesis) => {
              const isUsable =
                hypothesis.verdict === "signal" || hypothesis.verdict === "inverse_signal";
              return (
                <tr key={hypothesis.key} className="border-b border-rule align-top">
                  <td className="py-3 pe-4">
                    {hypothesis.title_en}
                    {hypothesis.note ? (
                      <div className="text-xs text-ink-muted">{hypothesis.note}</div>
                    ) : null}
                  </td>
                  <td className="py-3 pe-4 text-end tabular-nums text-ink-muted">
                    {hypothesis.n}
                  </td>
                  <td className="py-3 pe-4 text-end tabular-nums">
                    {Math.round(hypothesis.rate * 100)}%
                  </td>
                  <td className="py-3 pe-4 text-end tabular-nums text-ink-muted">
                    {Math.round(hypothesis.baseline * 100)}%
                    <div className="text-xs">{hypothesis.baseline_basis}</div>
                  </td>
                  <td className={`py-3 ${isUsable ? "text-accent" : "text-ink-muted"}`}>
                    {hypothesis.verdict_label}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <section className="mt-10 grid gap-8 md:grid-cols-2">
        <div>
          <h2 className="text-sm font-medium text-ink-muted">{t("letterTitle")}</h2>
          <div className="mt-3 grid gap-2">
            {letters.map(([label, count]) => (
              <div key={label} className="flex items-center gap-3">
                <span className="w-4 text-sm tabular-nums">{label}</span>
                <div className="min-w-0 flex-1">
                  <StackedBar
                    segments={[
                      { key: label, share: count / letterTotal, colorIndex: 0 },
                    ]}
                  />
                </div>
                <span className="w-14 text-end text-xs tabular-nums text-ink-muted">
                  {count} · {Math.round((count / letterTotal) * 100)}%
                </span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-ink-muted">
            {t("letterNote", { p: data.label_chi2_p.toFixed(3) })}
          </p>
        </div>

        <div>
          <h2 className="text-sm font-medium text-ink-muted">{t("archetypeTitle")}</h2>
          <div className="mt-3">
            <StackedBar
              height="1rem"
              segments={archetypes.map(([name, count], index) => ({
                key: name,
                share: count / archetypeTotal,
                colorIndex: index,
                label: bucketLabel(name),
              }))}
            />
            <Legend
              items={archetypes.map(([name], index) => ({
                key: name,
                label: bucketLabel(name),
                colorIndex: index,
              }))}
            />
          </div>
          <p className="mt-3 text-xs text-ink-muted">{t("archetypeNote")}</p>
        </div>
      </section>

      {/* The one genuinely actionable pattern on this page. */}
      <section className="mt-12">
        <h2 className="text-lg font-medium">{t("recurrenceTitle")}</h2>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">{t("recurrenceLede")}</p>

        <ul className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          {Object.entries(recurrence.curve).map(([threshold, count]) => (
            <li key={threshold}>
              <span className="tabular-nums">{count}</span>{" "}
              <span className="text-ink-muted">
                {t("curveItem", { threshold })}
              </span>
            </li>
          ))}
        </ul>

        <div className="mt-6 overflow-x-auto">
          <table className="w-full min-w-[32rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-rule text-ink-muted">
                <th className="py-2 pe-4 text-start font-medium">{t("colTopic")}</th>
                <th className="py-2 pe-4 text-end font-medium">{t("colQuestions")}</th>
                <th className="py-2 text-start font-medium">{t("colRepeatRate")}</th>
              </tr>
            </thead>
            <tbody>
              {recurrence.topics.slice(0, 12).map((topic) => (
                <tr key={topic.topic_id} className="border-b border-rule">
                  <td className="py-2 pe-4">
                    <Link
                      href={`/topics/${topic.topic_id}`}
                      className="hover:text-accent"
                    >
                      {topic.path.replaceAll("_", " ").replaceAll(".", " › ")}
                    </Link>
                  </td>
                  <td className="py-2 pe-4 text-end tabular-nums text-ink-muted">
                    {topic.questions}
                  </td>
                  <td className="py-2">
                    <span className="flex items-center gap-2">
                      <span className="inline-block h-2 w-24 overflow-hidden rounded-sm bg-rule">
                        <span
                          className="block h-full bg-accent"
                          style={{ width: `${topic.rate * 100}%` }}
                        />
                      </span>
                      <span className="tabular-nums">
                        {Math.round(topic.rate * 100)}%
                      </span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <p className="mt-8 max-w-2xl text-sm text-ink-muted">{t("footnote")}</p>
    </article>
  );
}
