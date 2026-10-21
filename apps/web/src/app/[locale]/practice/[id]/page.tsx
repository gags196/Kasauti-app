import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { ExamRunner } from "@/components/exam-runner";
import { ExamReview } from "@/components/exam-review";
import { ApiError, api, type PracticeSessionDetail } from "@/lib/api";
import { requireSessionToken } from "@/lib/session";

import { saveAnswer, submitPractice } from "../actions";

/**
 * One paper — being sat, or being reviewed.
 *
 * The same route serves both because they are the same object at two points in its life,
 * and `submitted_at` is what decides. That also means the answer key can only appear on
 * the reviewing side: the API strips it from an unsubmitted paper, so even a hand-built
 * request to this page cannot render an answer the learner has not earned yet.
 */
export default async function PracticeSessionPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("practice");

  const token = await requireSessionToken(locale);

  let session: PracticeSessionDetail;
  try {
    session = await api.practiceSession(token, id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError) return <ApiErrorNotice error={error} />;
    throw error;
  }

  if (session.submitted_at) {
    return <ExamReview session={session} locale={locale} />;
  }

  return (
    <article>
      <h1 className="text-lg font-medium">
        {session.mode === "year_paper"
          ? t("sittingYear", { year: session.year ?? 0 })
          : session.mode === "topic_drill"
            ? t("sittingDrill", { topic: session.topic_path ?? "" })
            : t("sittingMock", { count: session.question_count })}
      </h1>

      <div className="mt-6">
        <ExamRunner
          sessionId={session.id}
          questions={session.questions}
          durationSeconds={session.duration_seconds}
          startedAt={session.started_at}
          locale={locale}
          onSave={saveAnswer}
          onSubmit={submitPractice}
          labels={{
            questionOf: t("questionOf", { index: "{index}", total: "{total}" }),
            answeredOf: t("answeredOf", { answered: "{answered}", total: "{total}" }),
            previous: t("previous"),
            next: t("next"),
            clear: t("clear"),
            saving: t("saving"),
            submit: t("submit"),
            submitting: t("submitting"),
            confirmSubmit: t("confirmSubmit", { count: "{count}" }),
            negativeMarking: t("negativeMarking"),
            overtime: t("overtime"),
            passage: t("passage"),
            directions: t("directions"),
            figure: t("figure"),
          }}
        />
      </div>
    </article>
  );
}
