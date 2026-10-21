/**
 * Chart primitives, in CSS. No plotting library.
 *
 * Everything charted here is a share of a whole or a count per year over at most
 * fourteen bars, which flexbox draws exactly as well as a canvas would — and a chart
 * library would be the largest dependency in the app, shipped to a phone on a slow
 * connection to draw a bar. The palette comes from the same tokens as the rest of the
 * page, so a chart cannot drift away from the design in dark mode.
 *
 * Category colour is derived from the bucket's *position*, never from its name, so the
 * same bucket keeps the same colour across the year grid and the era table.
 */

/** Distinct hues at one lightness, so no category reads as more important than another.
 * The accent red is deliberately absent: it means "the official answer" everywhere else
 * in this app, and a category bar borrowing it would imply a correctness it does not have. */
const CATEGORY_HUES = [230, 160, 45, 300, 190, 100, 20, 270, 130, 330, 60, 210];

export function categoryColor(index: number): string {
  const hue = CATEGORY_HUES[index % CATEGORY_HUES.length];
  // Two lightness bands, so a thirteenth category is still distinguishable from the first.
  const band = Math.floor(index / CATEGORY_HUES.length) % 2;
  return `oklch(${band === 0 ? 62 : 76}% 0.12 ${hue})`;
}

/** One horizontal bar split into shares. Segments under a couple of percent are drawn
 * but carry no label — a legible chart with a legend beats an illegible self-labelling one. */
export function StackedBar({
  segments,
  height = "0.75rem",
}: {
  segments: { key: string; share: number; colorIndex: number; label?: string }[];
  height?: string;
}) {
  return (
    <div
      className="flex w-full overflow-hidden rounded-sm bg-rule"
      style={{ height }}
      role="img"
      aria-label={segments
        .filter((s) => s.share > 0)
        .map((s) => `${s.label ?? s.key} ${Math.round(s.share * 100)}%`)
        .join(", ")}
    >
      {segments
        .filter((segment) => segment.share > 0)
        .map((segment) => (
          <div
            key={segment.key}
            title={`${segment.label ?? segment.key} — ${Math.round(segment.share * 100)}%`}
            style={{
              width: `${segment.share * 100}%`,
              background: categoryColor(segment.colorIndex),
            }}
          />
        ))}
    </div>
  );
}

/** A count-per-year column chart. Zero years are drawn as an empty slot rather than
 * skipped: a sparkline that silently omits 2018 reads as continuity where there was a gap. */
export function YearBars({
  points,
  emptyLabel,
}: {
  points: { year: number; count: number }[];
  emptyLabel: string;
}) {
  const max = Math.max(1, ...points.map((p) => p.count));
  return (
    <div className="flex items-end gap-1" style={{ height: "4rem" }}>
      {points.map((point) => (
        <div key={point.year} className="flex min-w-0 flex-1 flex-col items-center gap-1">
          <div
            className={`w-full rounded-t-sm ${point.count ? "bg-accent" : "bg-rule"}`}
            style={{
              height: point.count
                ? `${Math.max(6, (point.count / max) * 48)}px`
                : "2px",
            }}
            title={
              point.count
                ? `${point.year}: ${point.count}`
                : `${point.year}: ${emptyLabel}`
            }
          />
          <span className="text-[0.6rem] tabular-nums text-ink-muted">
            {String(point.year).slice(2)}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { key: string; label: string; colorIndex: number }[] }) {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-ink-muted">
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block size-2.5 rounded-sm"
            style={{ background: categoryColor(item.colorIndex) }}
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/** Turns an enum-ish bucket key into something readable: `how_many_correct` →
 * "how many correct". Bucket labels that are already prose (the "(not classified)"
 * sentinels) pass through untouched. */
export function bucketLabel(key: string): string {
  return key.startsWith("(") ? key : key.replaceAll("_", " ");
}
