import { getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { Legend, categoryColor } from "@/components/bars";
import { Link } from "@/i18n/navigation";
import { ApiError, api, type RankingWindow, type Stage } from "@/lib/api";

type Search = { window?: string; stage?: string };

function parseWindow(value: string | undefined): RankingWindow {
  return value === "5y" ? "5y" : "all";
}

function parseStage(value: string | undefined): Stage | undefined {
  return value === "prelims" || value === "mains" ? value : undefined;
}

export default async function RankingsPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Search>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const sp = await searchParams;
  const t = await getTranslations("rankings");

  const window = parseWindow(sp.window);
  const stage = parseStage(sp.stage);

  let rankings;
  try {
    rankings = await api.rankings({ window, stage, limit: 50 });
  } catch (error) {
    if (error instanceof ApiError) return <ApiErrorNotice error={error} />;
    throw error;
  }

  const windowTabs = [
    { value: "all", label: t("windowAll") },
    { value: "5y", label: t("window5y") },
  ];
  const stageTabs = [
    { value: undefined, label: t("stageAll") },
    { value: "prelims", label: t("stagePrelims") },
    { value: "mains", label: t("stageMains") },
  ];

  const maxCount = Math.max(1, ...rankings.map((r) => r.question_count));

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-2 max-w-2xl text-ink-muted">{t("subtitle")}</p>

      <div className="mt-6 flex flex-wrap gap-6">
        <nav className="flex gap-1 rounded-lg border border-rule p-1">
          {windowTabs.map((tab) => (
            <Link
              key={tab.value}
              href={{ pathname: "/rankings", query: { window: tab.value, stage } }}
              className={`rounded-md px-3 py-1 text-sm ${
                window === tab.value ? "bg-accent-soft font-medium" : "text-ink-muted"
              }`}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
        <nav className="flex gap-1 rounded-lg border border-rule p-1">
          {stageTabs.map((tab) => (
            <Link
              key={tab.label}
              href={{ pathname: "/rankings", query: { window, stage: tab.value } }}
              className={`rounded-md px-3 py-1 text-sm ${
                stage === tab.value ? "bg-accent-soft font-medium" : "text-ink-muted"
              }`}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
        {!stage && (
          <Legend
            items={[
              { key: "prelims", label: t("stagePrelims"), colorIndex: 0 },
              { key: "mains", label: t("stageMains"), colorIndex: 1 },
            ]}
          />
        )}
      </div>

      {rankings.length === 0 ? (
        <p className="mt-10 rounded-lg border border-rule bg-paper-raised p-6 text-ink-muted">
          {t("empty")}
        </p>
      ) : (
        <div className="mt-6 overflow-hidden rounded-lg border border-rule bg-paper-raised">
          <div className="flex gap-4 border-b border-rule px-5 py-2 text-xs uppercase tracking-wide text-ink-muted">
            <span className="w-6 shrink-0" />
            <span className="min-w-0 flex-1">{t("colTopic")}</span>
            <span className="w-14 shrink-0 text-end">{t("colCount")}</span>
            <span className="w-14 shrink-0 text-end">{t("colLatest")}</span>
          </div>
          {!stage && (
            <p className="border-b border-rule px-5 py-2 text-xs text-ink-muted">
              {t("splitNote")}
            </p>
          )}
          <ol className="divide-y divide-rule">
          {rankings.map((row, index) => (
            <li key={row.topic_id}>
              <Link
                href={`/topics/${row.topic_id}`}
                className="flex items-center gap-4 px-5 py-3 hover:bg-accent-soft/40"
              >
                <span className="w-6 shrink-0 text-sm tabular-nums text-ink-muted">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    lang={locale}
                    className="block truncate text-sm"
                    title={locale === "hi" ? row.name_hi : row.name_en}
                  >
                    {locale === "hi" ? row.name_hi : row.name_en}
                  </span>
                  {/* Bar makes the distribution readable at a glance — the
                      whole point of the ranking is relative weight. Total length stays
                      proportional to the count either way; with no stage chosen it is
                      split rather than solid, because the same topic is asked in two
                      quite different exams and one bar spanning both would imply a
                      single thing was measured. */}
                  <span className="mt-1 flex h-1 overflow-hidden rounded-full bg-rule">
                    {stage ? (
                      <span
                        className="h-1 bg-accent"
                        style={{ width: `${(row.question_count / maxCount) * 100}%` }}
                      />
                    ) : (
                      <>
                        <span
                          className="h-1"
                          style={{
                            width: `${(row.prelims_count / maxCount) * 100}%`,
                            background: categoryColor(0),
                          }}
                        />
                        <span
                          className="h-1"
                          style={{
                            width: `${(row.mains_count / maxCount) * 100}%`,
                            background: categoryColor(1),
                          }}
                        />
                      </>
                    )}
                  </span>
                </span>
                <span className="w-14 shrink-0 text-end text-sm tabular-nums">
                  {stage ? (
                    row.question_count
                  ) : (
                    /* Two numbers, never their sum. */
                    <span className="flex flex-col leading-tight">
                      <span style={{ color: categoryColor(0) }}>{row.prelims_count}</span>
                      <span style={{ color: categoryColor(1) }}>{row.mains_count}</span>
                    </span>
                  )}
                </span>
                <span className="w-14 shrink-0 text-end text-sm tabular-nums text-ink-muted">
                  {row.latest_year}
                </span>
              </Link>
            </li>
          ))}
          </ol>
        </div>
      )}
    </div>
  );
}
