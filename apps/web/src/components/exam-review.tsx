import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import type { PracticeSessionDetail } from "@/lib/api";

/**
 * The scorecard, and the paper marked up.
 *
 * What a learner needs after a mock is not the number — it is *which* questions went
 * wrong and what the right answer was, next to the question they can then go and read
 * properly. So every question links back to its full page, where the topic tags, the
 * bilingual text and the Elimination Lab already live.
 *
 * The scorecard shows the negative-marking arithmetic rather than just the total,
 * because the lesson from a mock is usually about *how many guesses cost more than they
 * earned* — a fact the total alone hides.
 */
export async function ExamReview({
  session,
  locale,
}: {
  session: PracticeSessionDetail;
  locale: string;
}) {
  const t = await getTranslations("practice");
  const attempted = (session.correct_count ?? 0) + (session.wrong_count ?? 0);
  const accuracy = attempted ? (session.correct_count ?? 0) / attempted : 0;
  const penalty =
    session.negative_marking
      ? (session.wrong_count ?? 0) * (session.marks_per_question / 3)
      : 0;

  return (
    <article>
      <h1 className="text-2xl font-semibold tracking-tight">{t("resultTitle")}</h1>

      <dl className="mt-6 flex flex-wrap gap-x-10 gap-y-4">
        <div>
          <dt className="text-sm text-ink-muted">{t("score")}</dt>
          <dd className="text-3xl tabular-nums">
            {session.score?.toFixed(2)}
            <span className="text-lg text-ink-muted"> / {session.max_score}</span>
          </dd>
        </div>
        <div>
          <dt className="text-sm text-ink-muted">{t("accuracy")}</dt>
          <dd className="text-3xl tabular-nums">{Math.round(accuracy * 100)}%</dd>
        </div>
        <div>
          <dt className="text-sm text-ink-muted">{t("correct")}</dt>
          <dd className="text-3xl tabular-nums text-accent">{session.correct_count}</dd>
        </div>
        <div>
          <dt className="text-sm text-ink-muted">{t("wrong")}</dt>
          <dd className="text-3xl tabular-nums text-caution">{session.wrong_count}</dd>
        </div>
        <div>
          <dt className="text-sm text-ink-muted">{t("skipped")}</dt>
          <dd className="text-3xl tabular-nums text-ink-muted">
            {session.skipped_count}
          </dd>
        </div>
        {/* Paper II is qualifying, so its total is the wrong headline on its own: a
            candidate on 65 of 200 is out of the examination however well Paper I went.
            Absent for Paper I, which ranks. */}
        {session.qualifying_score !== null ? (
          <div>
            <dt className="text-sm text-ink-muted">{t("qualifying")}</dt>
            <dd
              className={`text-3xl tabular-nums ${
                session.qualified ? "text-accent" : "text-caution"
              }`}
            >
              {session.qualified ? t("qualified") : t("notQualified")}
            </dd>
          </div>
        ) : null}
      </dl>

      {session.qualifying_score !== null ? (
        <p className="mt-4 max-w-2xl text-sm text-ink-muted">
          {t("qualifyingNote", {
            mark: session.qualifying_score,
            max: session.max_score ?? 0,
          })}
        </p>
      ) : null}

      {/* The arithmetic, spelled out — the point of a mock is learning what guessing cost. */}
      <p className="mt-4 max-w-2xl text-sm text-ink-muted">
        {t("scoreExplainer", {
          correct: session.correct_count ?? 0,
          marks: session.marks_per_question,
          wrong: session.wrong_count ?? 0,
          penalty: penalty.toFixed(2),
        })}
      </p>
      {(session.unkeyed_count ?? 0) > 0 ? (
        <p className="mt-2 text-sm text-ink-muted">
          {t("droppedNote", { count: session.unkeyed_count ?? 0 })}
        </p>
      ) : null}

      <h2 className="mt-10 text-sm font-medium text-ink-muted">{t("reviewTitle")}</h2>
      <ol className="mt-3 grid gap-3">
        {session.questions.map((question) => {
          const state =
            question.selected_label === null
              ? "skipped"
              : question.is_correct
                ? "correct"
                : "wrong";
          return (
            <li
              key={question.id}
              className={`rounded-lg border p-4 ${
                state === "correct"
                  ? "border-accent/50"
                  : state === "wrong"
                    ? "border-caution/60"
                    : "border-rule"
              }`}
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                <span className="tabular-nums text-ink-muted">{question.index}.</span>
                <span
                  className={
                    state === "correct"
                      ? "text-accent"
                      : state === "wrong"
                        ? "text-caution"
                        : "text-ink-muted"
                  }
                >
                  {t(state)}
                </span>
                <span className="text-ink-muted">
                  {t("yourAnswer")}: {question.selected_label ?? "—"} ·{" "}
                  {t("officialAnswer")}: {question.correct_label ?? "—"}
                </span>
                <span className="text-ink-muted">
                  {question.year} · {t("questionNumber")} {question.question_number}
                </span>
              </div>
              <p lang={locale} className="mt-2 line-clamp-3 text-sm whitespace-pre-line">
                {locale === "hi" ? question.text_hi : question.text_en}
              </p>
              <Link
                href={`/pyq/${question.id}`}
                className="mt-2 inline-block text-sm text-accent hover:underline"
              >
                {t("openQuestion")}
              </Link>
            </li>
          );
        })}
      </ol>

      <div className="mt-8 flex flex-wrap gap-3">
        <Link
          href="/practice"
          className="rounded-full border border-accent bg-accent-soft px-4 py-2 text-sm text-accent"
        >
          {t("sitAnother")}
        </Link>
        <Link href="/me" className="rounded-full border border-rule px-4 py-2 text-sm">
          {t("seeProgress")}
        </Link>
      </div>
    </article>
  );
}
