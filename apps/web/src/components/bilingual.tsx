import { getLocale } from "next-intl/server";

import { MathText } from "./math-text";

/**
 * UPSC prints Hindi and English side by side on the same paper, and aspirants
 * routinely cross-check the other language for terminology. So both are shown:
 * the reader's locale leads, the other follows in a muted block — never hidden
 * behind an interaction, never dropped.
 *
 * Stems carry LaTeX verbatim (the Mathematics optional papers are almost nothing
 * else), so the text runs through {@link MathText}; `whitespace-pre-line` keeps the
 * paragraph breaks that come with it.
 */
export async function Bilingual({
  en,
  hi,
  className = "",
  emphasis = "normal",
}: {
  en?: string | null;
  hi?: string | null;
  className?: string;
  emphasis?: "normal" | "lead";
}) {
  const locale = await getLocale();
  const primaryLang = locale === "hi" ? "hi" : "en";
  const primary = primaryLang === "hi" ? hi : en;
  const secondary = primaryLang === "hi" ? en : hi;
  const secondaryLang = primaryLang === "hi" ? "en" : "hi";

  // Falls back gracefully: a question extracted in one language only still reads.
  const shown = primary ?? secondary;
  const shownLang = primary ? primaryLang : secondaryLang;
  if (!shown) return null;

  const size = emphasis === "lead" ? "text-lg" : "text-base";

  return (
    <div className={className}>
      <div
        lang={shownLang}
        className={`${size} whitespace-pre-line leading-relaxed`}
      >
        <MathText text={shown} />
      </div>
      {primary && secondary ? (
        <div
          lang={secondaryLang}
          className="mt-2 whitespace-pre-line border-s-2 border-rule ps-3 text-sm text-ink-muted"
        >
          <MathText text={secondary} />
        </div>
      ) : null}
    </div>
  );
}
