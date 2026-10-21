import { getLocale } from "next-intl/server";

import type { QuestionTable } from "@/lib/api";
import { MathText } from "./math-text";

/**
 * Renders a table printed inside a question — most often "Match List I with List II",
 * which appears in the majority of UPSC Prelims papers.
 *
 * Both languages are shown per cell, matching how the rest of the app treats bilingual
 * content: the reader's locale leads, the other follows muted.
 */
export async function QuestionTableView({ table }: { table: QuestionTable }) {
  const locale = await getLocale();
  const isHindi = locale === "hi";

  const primary = (cell: { text_en?: string | null; text_hi?: string | null }) =>
    (isHindi ? cell.text_hi : cell.text_en) ?? cell.text_en ?? cell.text_hi ?? "";
  const secondary = (cell: { text_en?: string | null; text_hi?: string | null }) => {
    const other = isHindi ? cell.text_en : cell.text_hi;
    return primary(cell) && other && other !== primary(cell) ? other : null;
  };

  const caption = isHindi ? table.caption_hi : table.caption_en;

  return (
    <figure className="mt-4">
      {caption ? (
        <figcaption lang={locale} className="mb-2 text-sm text-ink-muted">
          {caption}
        </figcaption>
      ) : null}
      {/* Wide tables scroll inside their own box; the page never scrolls sideways. */}
      <div className="overflow-x-auto rounded-lg border border-rule">
        <table className="w-full border-collapse text-sm">
          {table.headers.length > 0 ? (
            <thead>
              <tr className="border-b border-rule bg-accent-soft/40">
                {table.headers.map((cell, index) => (
                  <th
                    key={index}
                    scope="col"
                    lang={locale}
                    className="px-3 py-2 text-start align-top font-medium"
                  >
                    <MathText text={primary(cell)} />
                    {(() => {
                      const other = secondary(cell);
                      return other ? (
                        <span className="block text-xs font-normal text-ink-muted">
                          <MathText text={other} />
                        </span>
                      ) : null;
                    })()}
                  </th>
                ))}
              </tr>
            </thead>
          ) : null}
          <tbody className="divide-y divide-rule">
            {table.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} lang={locale} className="px-3 py-2 align-top">
                    <MathText text={primary(cell)} />
                    {(() => {
                      const other = secondary(cell);
                      return other ? (
                        <span className="block text-xs text-ink-muted">
                          <MathText text={other} />
                        </span>
                      ) : null;
                    })()}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
