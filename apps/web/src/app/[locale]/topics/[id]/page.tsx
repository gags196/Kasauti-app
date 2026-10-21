import { notFound } from "next/navigation";
import { getFormatter, getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { TopicDepth } from "@/components/topic-depth";
import { Link } from "@/i18n/navigation";
import {
  ApiError,
  api,
  type NoteContent,
  type PredictedAngle,
} from "@/lib/api";

export default async function TopicPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("topic");
  const tNav = await getTranslations("nav");
  const format = await getFormatter();

  const topicId = Number(id);
  if (!Number.isInteger(topicId)) notFound();

  let analysis;
  let note;
  let profile;
  let projection;
  try {
    [analysis, note, profile, projection] = await Promise.all([
      api.analysis(topicId),
      api.note(topicId),
      api.topicProfile(topicId),
      api.topicProjection(topicId),
    ]);
  } catch (error) {
    if (error instanceof ApiError) return <ApiErrorNotice error={error} />;
    throw error;
  }

  const isHindi = locale === "hi";
  const content = note
    ? ((isHindi ? note.content_hi : note.content_en) as unknown as NoteContent)
    : null;
  const angles = (analysis?.predicted_angles ?? []) as unknown as PredictedAngle[];
  const outcomes = analysis?.prediction_outcomes as
    | { hits?: number; misses?: number }
    | null
    | undefined;

  return (
    <div className="grid gap-12">
      {/* The measured picture leads. The model's read of the topic follows it, so a
          learner meets the evidence before anything generated from it. */}
      {profile ? <TopicDepth profile={profile} projection={projection} /> : null}

      <section>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{t("analysisTitle")}</h1>
          {analysis ? (
            <p className="text-sm text-ink-muted">
              {t("generatedFrom", { count: analysis.question_count })} ·{" "}
              {t("generatedOn", {
                date: format.dateTime(new Date(analysis.generated_at), {
                  dateStyle: "medium",
                }),
              })}
            </p>
          ) : null}
        </div>

        {!analysis ? (
          <p className="mt-4 rounded-lg border border-rule bg-paper-raised p-6 text-ink-muted">
            {t("noAnalysis")}
          </p>
        ) : (
          <>
            <p
              lang={locale}
              className="mt-4 max-w-3xl leading-relaxed"
            >
              {isHindi ? analysis.pattern_summary_hi : analysis.pattern_summary_en}
            </p>

            {angles.length > 0 ? (
              <div className="mt-8">
                <h2 className="text-sm font-medium text-ink-muted">
                  {t("predictedAngles")}
                </h2>
                <ol className="mt-3 grid gap-3">
                  {angles.map((angle, index) => (
                    <li
                      key={angle.angle_en}
                      className="rounded-lg border border-rule bg-paper-raised p-5"
                    >
                      <p className="flex gap-3">
                        <span className="tabular-nums text-ink-muted">{index + 1}.</span>
                        <span lang={locale}>
                          {isHindi ? angle.angle_hi : angle.angle_en}
                        </span>
                      </p>
                      {angle.rationale_en ? (
                        <p className="mt-2 ps-7 text-sm text-ink-muted">
                          <span className="font-medium">{t("rationale")}:</span>{" "}
                          {angle.rationale_en}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ol>

                {/* Predictions ship with their own visible record — an honest
                    hit rate rather than an unverified claim. */}
                <p className="mt-4 text-sm text-ink-muted">
                  {outcomes && (outcomes.hits ?? 0) + (outcomes.misses ?? 0) > 0
                    ? t("hitRate", {
                        hits: outcomes.hits ?? 0,
                        misses: outcomes.misses ?? 0,
                      })
                    : t("hitRateNone")}
                </p>
              </div>
            ) : null}
          </>
        )}
      </section>

      <section>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">{t("noteTitle")}</h2>
          {note ? (
            <p className="text-sm text-ink-muted">
              {t("generatedFrom", { count: note.question_count })}
            </p>
          ) : null}
        </div>

        {!content ? (
          <p className="mt-4 rounded-lg border border-rule bg-paper-raised p-6 text-ink-muted">
            {t("noNote")}
          </p>
        ) : (
          <article
            lang={locale}
            className="mt-4 rounded-lg border border-rule bg-paper-raised p-6"
          >
            <h3 className="text-lg font-medium">{content.title}</h3>
            <p className="mt-2 text-ink-muted">{content.overview}</p>

            <div className="mt-6 grid gap-6">
              {content.sections.map((section) => (
                <div key={section.heading}>
                  <h4 className="text-sm font-medium text-ink-muted">
                    {section.heading}
                  </h4>
                  <ul className="mt-2 grid gap-1.5">
                    {section.points.map((point) => (
                      <li key={point} className="flex gap-2.5">
                        <span aria-hidden className="text-accent">
                          •
                        </span>
                        <span>{point}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            {content.keywords.length > 0 ? (
              <div className="mt-6 border-t border-rule pt-4">
                <h4 className="text-sm font-medium text-ink-muted">{t("keywords")}</h4>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {content.keywords.map((keyword) => (
                    <li
                      key={keyword}
                      className="rounded-full bg-accent-soft px-2.5 py-0.5 text-sm"
                    >
                      {keyword}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </article>
        )}
      </section>

      <Link href="/rankings" className="text-sm text-ink-muted hover:text-ink">
        ← {tNav("rankings")}
      </Link>
    </div>
  );
}
