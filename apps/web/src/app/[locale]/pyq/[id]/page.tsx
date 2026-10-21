import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { Bilingual } from "@/components/bilingual";
import { EliminationLab } from "@/components/elimination-lab";
import { QuestionTableView } from "@/components/question-table";
import { StimulusBlock } from "@/components/stimulus";
import { Link } from "@/i18n/navigation";
import { ApiError, api, type QuestionTable } from "@/lib/api";
import { ELIMINATION_COOKIE, isEliminationEnabled } from "@/lib/elimination-mode";

export default async function QuestionPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("question");

  const questionId = Number(id);
  if (!Number.isInteger(questionId)) notFound();

  let question;
  try {
    question = await api.question(questionId);
  } catch (error) {
    if (error instanceof ApiError) return <ApiErrorNotice error={error} />;
    throw error;
  }
  if (!question) notFound();

  // Elimination Lab mode is off by default, and when it is off nothing is fetched —
  // that is the difference between a mode and a panel that is merely collapsed.
  const labEnabled = isEliminationEnabled(
    (await cookies()).get(ELIMINATION_COOKIE)?.value,
  );
  const lab = labEnabled ? await api.questionLab(questionId) : null;

  // Correctness only ever comes from an official answer key; until one is
  // loaded every option is is_correct: null and we say so rather than guess.
  const hasAnswerKey = question.options.some((option) => option.is_correct !== null);

  return (
    <article>
      <Link href="/pyq" className="text-sm text-ink-muted hover:text-ink">
        ← {t("backToSearch")}
      </Link>

      <dl className="mt-6 flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <div>
          <dt className="text-ink-muted">{t("year")}</dt>
          <dd className="tabular-nums">{question.year}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">{t("number")}</dt>
          <dd>{question.question_number}</dd>
        </div>
        {question.marks ? (
          <div>
            <dt className="text-ink-muted">{t("marks")}</dt>
            <dd className="tabular-nums">{question.marks}</dd>
          </div>
        ) : null}
      </dl>

      <div className="mt-6 rounded-lg border border-rule bg-paper-raised p-6">
        <StimulusBlock
          stimulus={question.stimulus}
          locale={locale}
          labels={{ passage: t("passage"), directions: t("directions"), figure: t("figure") }}
        />
        <Bilingual en={question.text_en} hi={question.text_hi} emphasis="lead" />
        {question.math_latex ? (
          <pre className="latex mt-4 rounded border border-rule p-3 text-ink-muted">
            {question.math_latex}
          </pre>
        ) : null}
        {(question.tables as unknown as QuestionTable[]).map((table, index) => (
          <QuestionTableView key={index} table={table} />
        ))}
      </div>

      {question.options.length > 0 ? (
        <section className="mt-8">
          <h2 className="text-sm font-medium text-ink-muted">{t("options")}</h2>
          <ol className="mt-3 grid gap-2">
            {question.options.map((option) => (
              <li
                key={option.label}
                className={`flex gap-3 rounded-lg border p-4 ${
                  option.is_correct
                    ? "border-accent bg-accent-soft"
                    : "border-rule bg-paper-raised"
                }`}
              >
                <span className="font-medium tabular-nums">{option.label}.</span>
                <div className="min-w-0 flex-1">
                  <Bilingual en={option.text_en} hi={option.text_hi} />
                </div>
                {option.is_correct ? (
                  <span className="shrink-0 self-start text-xs font-medium text-accent">
                    {t("correct")}
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
          {!hasAnswerKey ? (
            <p className="mt-3 text-sm text-ink-muted">{t("answerKeyPending")}</p>
          ) : null}
        </section>
      ) : null}

      {lab ? <EliminationLab lab={lab} /> : null}

      {question.topic_paths.length > 0 ? (
        <section className="mt-8">
          <h2 className="text-sm font-medium text-ink-muted">{t("topics")}</h2>
          <ul className="mt-3 flex flex-wrap gap-2">
            {question.topic_paths.map((path) => (
              <li
                key={path}
                className="rounded-full border border-rule bg-paper-raised px-3 py-1 text-sm"
              >
                {path.replaceAll("_", " ").replaceAll(".", " › ")}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}
