import { getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { Link, redirect } from "@/i18n/navigation";
import { ApiError, api, type Me, type Performance } from "@/lib/api";
import { requireSessionToken } from "@/lib/session";

import { signOut } from "../account/actions";

/**
 * The learner's own record.
 *
 * Everything else in this product describes the *exam*. This page is the only one that
 * describes the *person*, and it is deliberately small: attempts, accuracy, the topics
 * they get wrong, the papers they have sat. No streak, no XP, no rank.
 *
 * The weak-topic list has a floor of four graded attempts per topic (`practice.py`).
 * Below that a percentage is a bad afternoon rather than a weakness, and pointing a
 * learner at a topic because they missed one question would waste the week they then
 * spend on it.
 */
export default async function MePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("me");

  const token = await requireSessionToken(locale);

  let me: Me;
  let performance: Performance;
  try {
    [me, performance] = await Promise.all([api.me(token), api.performance(token)]);
  } catch (error) {
    // A token that is expired or was signed with a rotated secret reads as 401. Clearing
    // it and showing the login form beats an error page the learner cannot act on.
    if (error instanceof ApiError && error.status === 401) {
      redirect({ href: "/account/login", locale });
    }
    if (error instanceof ApiError) return <ApiErrorNotice error={error} />;
    throw error;
  }

  const hasData = performance.questions_attempted > 0;

  return (
    <article>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("title", { name: me.name || me.email })}
        </h1>
        <form action={signOut}>
          <button
            type="submit"
            className="rounded-full border border-rule px-3 py-1 text-sm text-ink-muted hover:text-ink"
          >
            {t("signOut")}
          </button>
        </form>
      </div>

      {!hasData ? (
        <div className="mt-8 rounded-lg border border-dashed border-rule p-6">
          <p className="text-ink-muted">{t("empty")}</p>
          <Link
            href="/practice"
            className="mt-4 inline-block rounded-full border border-accent bg-accent-soft px-4 py-2 text-sm text-accent"
          >
            {t("startPractice")}
          </Link>
        </div>
      ) : (
        <>
          <dl className="mt-8 flex flex-wrap gap-x-10 gap-y-4">
            <div>
              <dt className="text-sm text-ink-muted">{t("attempted")}</dt>
              <dd className="text-3xl tabular-nums">
                {performance.questions_attempted}
              </dd>
            </div>
            <div>
              <dt className="text-sm text-ink-muted">{t("accuracy")}</dt>
              <dd className="text-3xl tabular-nums">
                {Math.round(performance.accuracy * 100)}%
              </dd>
            </div>
            <div>
              <dt className="text-sm text-ink-muted">{t("papersSat")}</dt>
              <dd className="text-3xl tabular-nums">
                {performance.submitted_sessions}
              </dd>
            </div>
          </dl>

          {performance.weak_topics.length > 0 ? (
            <section className="mt-10">
              <h2 className="text-sm font-medium text-ink-muted">{t("weakTitle")}</h2>
              <p className="mt-1 text-xs text-ink-muted">{t("weakNote")}</p>
              <ul className="mt-3 grid gap-2">
                {performance.weak_topics.map((topic) => (
                  <li
                    key={topic.topic_id}
                    className="flex flex-wrap items-center gap-3 rounded-lg border border-rule bg-paper-raised p-3 text-sm"
                  >
                    <Link
                      href={`/topics/${topic.topic_id}`}
                      className="min-w-0 flex-1 hover:text-accent"
                    >
                      {locale === "hi" ? topic.name_hi : topic.name_en}
                    </Link>
                    <span className="inline-block h-2 w-28 overflow-hidden rounded-sm bg-rule">
                      <span
                        className="block h-full bg-caution"
                        style={{ width: `${topic.accuracy * 100}%` }}
                      />
                    </span>
                    <span className="w-24 text-end tabular-nums text-ink-muted">
                      {topic.correct}/{topic.attempted} ·{" "}
                      {Math.round(topic.accuracy * 100)}%
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            <p className="mt-8 text-sm text-ink-muted">{t("notEnoughForWeak")}</p>
          )}

          {performance.strong_topics.length > 0 ? (
            <section className="mt-8">
              <h2 className="text-sm font-medium text-ink-muted">{t("strongTitle")}</h2>
              <ul className="mt-3 flex flex-wrap gap-2">
                {performance.strong_topics.map((topic) => (
                  <li key={topic.topic_id}>
                    <Link
                      href={`/topics/${topic.topic_id}`}
                      className="inline-block rounded-full border border-rule px-3 py-1 text-sm hover:border-ink"
                    >
                      {locale === "hi" ? topic.name_hi : topic.name_en}{" "}
                      <span className="tabular-nums text-ink-muted">
                        {Math.round(topic.accuracy * 100)}%
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}

      {performance.recent_sessions.length > 0 ? (
        <section className="mt-10">
          <h2 className="text-sm font-medium text-ink-muted">{t("recentTitle")}</h2>
          <ul className="mt-3 grid gap-2">
            {performance.recent_sessions.map((session) => (
              <li key={session.id}>
                <Link
                  href={`/practice/${session.id}`}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-rule bg-paper-raised p-3 text-sm hover:border-ink"
                >
                  <span className="min-w-0 flex-1">
                    {session.mode === "year_paper"
                      ? t("modeYear", { year: session.year ?? 0 })
                      : session.mode === "topic_drill"
                        ? t("modeDrill", { topic: session.topic_path ?? "" })
                        : t("modeMock", { count: session.question_count })}
                  </span>
                  <span className="tabular-nums text-ink-muted">
                    {session.submitted_at
                      ? `${session.score} / ${session.max_score}`
                      : t("inProgress")}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}
