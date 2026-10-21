import { getTranslations, setRequestLocale } from "next-intl/server";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { Legend, StackedBar, bucketLabel, categoryColor } from "@/components/bars";
import { Link } from "@/i18n/navigation";
import { ApiError, api, type TrendDimension, type Trends } from "@/lib/api";

/**
 * How the paper itself has changed, year by year — the founder's second question
 * ("most recent trends will tell the pattern of questions from past 5 years").
 *
 * The headline this page exists to carry: the "How many of the above are correct?"
 * format went from **zero occurrences before 2022** to a fifth of the paper. That single
 * fact is why every analysis in this product is era-aware, and why a fourteen-year
 * average is shown as context rather than as the answer.
 *
 * Only the two dimensions derived from the printed page are offered. `format` and
 * `depth` come from a classification pass that has not run, and a toggle leading to an
 * empty chart is worse than no toggle.
 */
const DIMENSIONS: { key: TrendDimension; labelKey: "dimMarker" | "dimOptions" }[] = [
  { key: "regex_format", labelKey: "dimMarker" },
  { key: "archetype", labelKey: "dimOptions" },
];

export default async function TrendsPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ dimension?: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("trends");
  const { dimension: raw } = await searchParams;

  const dimension: TrendDimension =
    DIMENSIONS.find((d) => d.key === raw)?.key ?? "regex_format";

  let data: Trends;
  try {
    // Both dimensions are derived from a printed MCQ, so this chart is about Prelims.
    // The API defaults to prelims too; saying it here keeps the page honest about what
    // it is drawing rather than relying on a default it does not name.
    data = await api.trends({ dimension, stage: "prelims" });
  } catch (error) {
    if (error instanceof ApiError) return <ApiErrorNotice error={error} />;
    throw error;
  }

  // Colour by position in the bucket list, so a bucket keeps its colour between the
  // year grid and the era table below it.
  const colorOf = new Map(data.buckets.map((bucket, index) => [bucket, index]));
  const shareOf = (year: number, bucket: string) =>
    data.cells.find((c) => c.year === year && c.bucket === bucket)?.share ?? 0;

  const biggestMovers = data.shifts.slice(0, 8);

  return (
    <article>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-2 max-w-2xl text-ink-muted">{t("lede")}</p>

      <nav className="mt-6 flex flex-wrap gap-2">
        {DIMENSIONS.map((option) => (
          <Link
            key={option.key}
            href={{ pathname: "/trends", query: { dimension: option.key } }}
            className={`rounded-full border px-3 py-1 text-sm ${
              option.key === dimension
                ? "border-accent bg-accent-soft text-accent"
                : "border-rule text-ink-muted hover:border-ink hover:text-ink"
            }`}
          >
            {t(option.labelKey)}
          </Link>
        ))}
      </nav>

      {/* The era comparison first: it is the finding, and the year grid is the evidence. */}
      <section className="mt-8">
        <h2 className="text-sm font-medium text-ink-muted">{t("shiftTitle")}</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[34rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-rule text-ink-muted">
                <th className="py-2 pe-4 text-start font-medium">{t("colBucket")}</th>
                <th className="py-2 pe-4 text-end font-medium">{t("colLegacy")}</th>
                <th className="py-2 pe-4 text-end font-medium">{t("colRecent")}</th>
                <th className="py-2 text-start font-medium">{t("colDelta")}</th>
              </tr>
            </thead>
            <tbody>
              {biggestMovers.map((shift) => {
                const delta = shift.recent_share - shift.legacy_share;
                return (
                  <tr key={shift.bucket} className="border-b border-rule">
                    <td className="py-2 pe-4">
                      <span className="flex items-center gap-2">
                        <span
                          aria-hidden
                          className="inline-block size-2.5 shrink-0 rounded-sm"
                          style={{
                            background: categoryColor(colorOf.get(shift.bucket) ?? 0),
                          }}
                        />
                        {bucketLabel(shift.bucket)}
                      </span>
                    </td>
                    <td className="py-2 pe-4 text-end tabular-nums text-ink-muted">
                      {Math.round(shift.legacy_share * 100)}%
                    </td>
                    <td className="py-2 pe-4 text-end tabular-nums">
                      {Math.round(shift.recent_share * 100)}%
                    </td>
                    <td className="py-2">
                      <span
                        className={`tabular-nums ${
                          delta > 0.02
                            ? "text-accent"
                            : delta < -0.02
                              ? "text-caution"
                              : "text-ink-muted"
                        }`}
                      >
                        {delta > 0 ? "+" : ""}
                        {Math.round(delta * 100)} pp
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="text-sm font-medium text-ink-muted">{t("yearTitle")}</h2>
        <div className="mt-3 grid gap-2">
          {data.years.map((year) => (
            <div key={year} className="flex items-center gap-3">
              <span className="w-10 shrink-0 text-sm tabular-nums text-ink-muted">
                {year}
              </span>
              <div className="min-w-0 flex-1">
                <StackedBar
                  segments={data.buckets.map((bucket) => ({
                    key: bucket,
                    share: shareOf(year, bucket),
                    colorIndex: colorOf.get(bucket) ?? 0,
                    label: bucketLabel(bucket),
                  }))}
                />
              </div>
              <span className="w-10 shrink-0 text-end text-xs tabular-nums text-ink-muted">
                {data.total_by_year[String(year)] ?? 0}
              </span>
            </div>
          ))}
        </div>
        <Legend
          items={data.buckets.map((bucket, index) => ({
            key: bucket,
            label: bucketLabel(bucket),
            colorIndex: index,
          }))}
        />
        {/* Coverage is stated, never implied. */}
        {data.note ? <p className="mt-4 text-xs text-ink-muted">{data.note}</p> : null}
      </section>

      <p className="mt-8 text-sm text-ink-muted">{t("footnote")}</p>
    </article>
  );
}
