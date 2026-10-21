import { getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { ApiError, api, type RuleStat } from "@/lib/api";

/**
 * The scoreboard behind Elimination Lab mode: every shortcut rule the coaching circuit
 * teaches, with what it actually does across 1,400 keyed questions.
 *
 * Two eras are shown side by side and that is the point of the page. Pooled over
 * fourteen years exactly one rule reaches significance; over the 2022-onwards exam none
 * does. A learner who only ever saw the pooled column would take away the opposite
 * lesson from the one the data supports.
 */
export default async function EliminationPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("eliminationPage");

  let all: RuleStat[];
  let recent: RuleStat[];
  try {
    [all, recent] = await Promise.all([
      api.eliminationRules("all"),
      api.eliminationRules("recent"),
    ]);
  } catch (error) {
    if (error instanceof ApiError) return <ApiErrorNotice error={error} />;
    throw error;
  }

  const recentByKey = new Map(recent.map((rule) => [rule.key, rule]));
  const usableAll = all.filter((r) => r.verdict === "signal" || r.verdict === "inverse_signal");
  const usableRecent = recent.filter(
    (r) => r.verdict === "signal" || r.verdict === "inverse_signal",
  );

  return (
    <article>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-2 max-w-2xl text-ink-muted">{t("lede")}</p>

      <dl className="mt-6 flex flex-wrap gap-x-10 gap-y-3 text-sm">
        <div>
          <dt className="text-ink-muted">{t("headlineAll")}</dt>
          <dd className="text-lg tabular-nums">
            {usableAll.length} / {all.length}
          </dd>
        </div>
        <div>
          <dt className="text-ink-muted">{t("headlineRecent")}</dt>
          <dd className="text-lg tabular-nums">
            {usableRecent.length} / {recent.length}
          </dd>
        </div>
      </dl>

      <div className="mt-8 overflow-x-auto">
        <table className="w-full min-w-[46rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-start text-ink-muted">
              <th className="py-2 pe-4 text-start font-medium">{t("colRule")}</th>
              <th className="py-2 pe-4 text-start font-medium">{t("colClaim")}</th>
              <th className="py-2 pe-4 text-end font-medium">{t("colMeasured")}</th>
              <th className="py-2 pe-4 text-end font-medium">{t("colRecent")}</th>
              <th className="py-2 text-start font-medium">{t("colVerdict")}</th>
            </tr>
          </thead>
          <tbody>
            {all.map((rule) => {
              const inRecent = recentByKey.get(rule.key);
              const usable = rule.verdict === "signal" || rule.verdict === "inverse_signal";
              return (
                <tr key={rule.key} className="border-b border-rule align-top">
                  <td className="py-3 pe-4">{rule.title_en}</td>
                  <td className="py-3 pe-4 text-ink-muted">{rule.docx_claim}</td>
                  <td className="py-3 pe-4 text-end tabular-nums">
                    {rule.n > 0 ? (
                      <>
                        {Math.round(rule.rate * 100)}%
                        <span className="text-ink-muted">
                          {" "}
                          / {Math.round(rule.baseline * 100)}%
                        </span>
                        <div className="text-xs text-ink-muted">n = {rule.n}</div>
                      </>
                    ) : (
                      <span className="text-ink-muted">—</span>
                    )}
                  </td>
                  <td className="py-3 pe-4 text-end tabular-nums">
                    {inRecent && inRecent.n > 0 ? (
                      <>
                        {Math.round(inRecent.rate * 100)}%
                        <div className="text-xs text-ink-muted">n = {inRecent.n}</div>
                      </>
                    ) : (
                      <span className="text-ink-muted">—</span>
                    )}
                  </td>
                  {/* Both verdicts, always. The one rule that reaches significance does
                      so on pre-2022 papers and is flat afterwards, so an all-years
                      verdict shown alone would sell exactly the rule the data kills. */}
                  <td className={`py-3 ${usable ? "text-accent" : "text-ink-muted"}`}>
                    {rule.verdict_label}
                    {inRecent ? (
                      <div className="text-xs text-ink-muted">
                        {t("recentVerdict", { verdict: inRecent.verdict_label })}
                      </div>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <section className="mt-8 max-w-2xl text-sm text-ink-muted">
        <h2 className="font-medium text-ink">{t("methodTitle")}</h2>
        <ul className="mt-2 grid gap-2">
          <li>{t("methodBaseline")}</li>
          <li>{t("methodBonferroni")}</li>
          <li>{t("methodDirection")}</li>
          <li>{t("methodUntestable")}</li>
        </ul>
      </section>
    </article>
  );
}
