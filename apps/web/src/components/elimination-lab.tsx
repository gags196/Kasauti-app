import { getTranslations } from "next-intl/server";

import type { LabFiring, QuestionLab } from "@/lib/api";

/**
 * The Elimination Lab panel: what the coaching shortcuts would have told a candidate on
 * this question, beside what the official key says.
 *
 * The rules do not work — one of fifteen reaches significance over fourteen years and
 * none over the 2022-onwards exam. So this panel is deliberately *not* an advisor. Three
 * rules of presentation follow from that, and none is cosmetic:
 *
 * 1. **Every firing shows its outcome against the key**, so "eliminate statement 2" is
 *    always accompanied by whether statement 2 was in fact false.
 * 2. **Every firing shows the rule's measured rate and verdict.** A learner can never see
 *    a shortcut fire without seeing how often it is right across 1,400 questions.
 * 3. **A shortcut that would have cost a mark is styled as the failure it is**, in
 *    caution colour rather than softened into a footnote.
 *
 * The analysis runs on the English text, because the rules are claims about English
 * wording; the panel says so rather than implying the Hindi twin was checked too.
 */

/** The decoder's reasons, mapped to messages. Anything unmapped falls back to a generic
 * line rather than printing an internal string at a learner. */
const SKIP_KEYS: Record<string, string> = {
  "no numbered statements": "noStatements",
  "count question, partial information": "partialCount",
  "negative polarity": "negativePolarity",
  "unkeyed or dropped": "unkeyed",
  "no English stem": "noEnglish",
  "options are not statement references": "notStatements",
  "options reference a statement that is not printed": "misprinted",
  "options reference no statement": "notStatements",
};

export async function EliminationLab({ lab }: { lab: QuestionLab }) {
  const t = await getTranslations("lab");

  if (!lab.decodable) {
    const key = SKIP_KEYS[lab.skipped_reason ?? ""] ?? "unknown";
    return (
      <section className="mt-8 rounded-lg border border-dashed border-rule p-5">
        <h2 className="text-sm font-medium text-ink-muted">{t("title")}</h2>
        <p className="mt-2 text-sm text-ink-muted">{t(`skipped.${key}`)}</p>
      </section>
    );
  }

  const byStatement = new Map<number, LabFiring[]>();
  for (const firing of lab.firings) {
    if (firing.statement_index === null) continue;
    const list = byStatement.get(firing.statement_index) ?? [];
    list.push(firing);
    byStatement.set(firing.statement_index, list);
  }
  const optionFirings = lab.firings.filter((f) => f.option_label !== null);

  return (
    <section className="mt-8 rounded-lg border border-rule bg-paper-raised p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">{t("title")}</h2>
        <p className="text-sm text-ink-muted">
          {t("scoreline", { helped: lab.helped, misled: lab.misled })}
        </p>
      </div>
      <p className="mt-2 text-sm text-ink-muted">{t("lede")}</p>

      <ol className="mt-4 grid gap-3">
        {lab.statements.map((statement) => (
          <li key={statement.index} className="rounded-lg border border-rule p-4">
            <div className="flex gap-3">
              <span className="font-medium tabular-nums">{statement.index}.</span>
              <div className="min-w-0 flex-1">
                <p lang="en" className="leading-relaxed">
                  {statement.text}
                </p>
                <p
                  className={`mt-2 text-xs font-medium ${
                    statement.is_true ? "text-accent" : "text-ink-muted"
                  }`}
                >
                  {statement.is_true ? t("keyTrue") : t("keyFalse")}
                </p>
                {(byStatement.get(statement.index) ?? []).length > 0 ? (
                  <ul className="mt-3 grid gap-2">
                    {(byStatement.get(statement.index) ?? []).map((firing) => (
                      <FiringRow key={`${firing.rule_key}-${statement.index}`} firing={firing} />
                    ))}
                  </ul>
                ) : (
                  <p className="mt-3 text-xs text-ink-muted">{t("noRuleFired")}</p>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>

      {optionFirings.length > 0 ? (
        <ul className="mt-3 grid gap-2">
          {optionFirings.map((firing) => (
            <FiringRow key={`${firing.rule_key}-${firing.option_label}`} firing={firing} />
          ))}
        </ul>
      ) : null}

      <p className="mt-4 text-xs text-ink-muted">{t("englishOnly")}</p>
    </section>
  );
}

async function FiringRow({ firing }: { firing: LabFiring }) {
  const t = await getTranslations("lab");
  const helped = firing.outcome === "helped";
  const target =
    firing.option_label !== null
      ? t("adviceOption", { label: firing.option_label })
      : t(firing.advice === "eliminate" ? "adviceEliminate" : "adviceKeep");

  return (
    <li className="rounded border border-rule p-3 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className={`text-xs font-medium ${helped ? "text-accent" : "text-caution"}`}>
          {helped ? t("helped") : t("misled")}
        </span>
        <span className="text-ink-muted">·</span>
        <span>{target}</span>
      </div>
      <p className="mt-1 text-ink-muted">{firing.title_en}</p>
      <p className="mt-1 text-xs text-ink-muted">{t("claims", { claim: firing.docx_claim })}</p>
      {firing.measured_rate !== null && firing.measured_n > 0 ? (
        <p className="mt-1 text-xs">
          {t("measured", {
            rate: Math.round(firing.measured_rate * 100),
            baseline: Math.round((firing.measured_baseline ?? 0) * 100),
            n: firing.measured_n,
          })}{" "}
          <span className="text-ink-muted">{t(`verdict.${firing.measured_verdict ?? "noise"}`)}</span>
        </p>
      ) : null}
    </li>
  );
}
