import { getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { QuestionCard } from "@/components/question-card";
import { SearchForm } from "@/components/search-form";
import { Link } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";

type Search = { q?: string; from?: string; to?: string; topic?: string };

function year(value: string | undefined): number | undefined {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 1900 ? parsed : undefined;
}

export default async function PyqPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Search>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const sp = await searchParams;
  const t = await getTranslations("pyq");

  const query = sp.q?.trim() ?? "";

  let results = null;
  let topTopics = null;
  try {
    // With no query there is nothing to search, so offer the most-asked topics
    // as an entry point instead of an empty page.
    [results, topTopics] = await Promise.all([
      query.length >= 2
        ? api.search({
            query,
            topic_path: sp.topic,
            year_from: year(sp.from),
            year_to: year(sp.to),
          })
        : Promise.resolve(null),
      query.length >= 2 ? Promise.resolve(null) : api.rankings({ window: "all", limit: 8 }),
    ]);
  } catch (error) {
    if (error instanceof ApiError) return <ApiErrorNotice error={error} />;
    throw error;
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-2 max-w-2xl text-ink-muted">{t("subtitle")}</p>

      <SearchForm defaults={{ q: sp.q, from: sp.from, to: sp.to }} />

      {results ? (
        <>
          <p className="mt-8 text-sm text-ink-muted">
            {t("resultCount", { count: results.length })}
          </p>
          {results.length === 0 ? (
            <p className="mt-4 rounded-lg border border-rule bg-paper-raised p-6 text-ink-muted">
              {t("emptyResults")}
            </p>
          ) : (
            <div className="mt-4 grid gap-4">
              {results.map((hit) => (
                <QuestionCard
                  key={hit.question.id}
                  question={hit.question}
                  score={hit.score}
                />
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="mt-10">
          <p className="text-ink-muted">{t("emptyPrompt")}</p>
          {topTopics && topTopics.length > 0 ? (
            <>
              <h2 className="mt-8 text-sm font-medium text-ink-muted">
                {t("browseTopTopics")}
              </h2>
              <ul className="mt-3 flex flex-wrap gap-2">
                {topTopics.map((topic) => (
                  <li key={topic.topic_id}>
                    <Link
                      href={`/topics/${topic.topic_id}`}
                      lang={locale}
                      className="inline-block rounded-full border border-rule bg-paper-raised px-3 py-1.5 text-sm hover:border-ink"
                    >
                      {locale === "hi" ? topic.name_hi : topic.name_en}
                      <span className="ms-2 tabular-nums text-ink-muted">
                        {topic.question_count}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
