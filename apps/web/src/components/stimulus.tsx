import type { Question } from "@/lib/api";

/**
 * The passage or shared directions block an item is answered from.
 *
 * Prelims Paper II prints one comprehension passage above two to five items, and one
 * option key above a run of data-sufficiency items. The corpus stores each block once
 * (`question_stimuli`) rather than copying it into every stem, so it has to be
 * re-attached here — and it is shown *above* the item, in the order the booklet prints
 * it, because a comprehension item read without its passage is not a question at all.
 *
 * Deliberately not a server component: the exam runner is a client component and needs
 * the same block, and a second, near-identical implementation would drift. Locale comes
 * in as a prop for the same reason, so both callers render the two languages the same
 * way `bilingual.tsx` does — reader's locale leading, the other following muted.
 *
 * A `kind === "figure"` stimulus (route-counting grids, growth curves — diagrams whose
 * content is its shape, with no printed numbers to fall back on as a table) has no
 * passage text to lead with; `text_en`/`text_hi` there are alt text, shown as a caption
 * below the image rather than as the primary content. The image URL is built from
 * `NEXT_PUBLIC_API_BASE_URL` rather than going through `lib/api.ts`'s typed fetch layer:
 * an `<img src>` is fetched by the browser directly, in both a server-rendered page and
 * this client component, so it needs a browser-visible constant rather than a request
 * wrapper meant for JSON.
 */
export function StimulusBlock({
  stimulus,
  locale,
  labels,
}: {
  stimulus: NonNullable<Question["stimulus"]> | null | undefined;
  locale: string;
  labels: { passage: string; directions: string; figure: string };
}) {
  if (!stimulus) return null;

  const primaryLang = locale === "hi" ? "hi" : "en";
  const secondaryLang = primaryLang === "hi" ? "en" : "hi";
  const primary = primaryLang === "hi" ? stimulus.text_hi : stimulus.text_en;
  const secondary = primaryLang === "hi" ? stimulus.text_en : stimulus.text_hi;

  if (stimulus.kind === "figure") {
    const caption = primary ?? secondary;
    return (
      <section className="mb-4 rounded-lg border border-rule border-s-4 border-s-ink-muted bg-paper p-5">
        <h2 className="mb-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
          {labels.figure}
        </h2>
        {/* eslint-disable-next-line @next/next/no-img-element -- cross-origin API asset, not a local/optimizable image */}
        <img
          src={`${process.env.NEXT_PUBLIC_API_BASE_URL ?? ""}/api/v1/pyq/figures/${stimulus.id}`}
          alt={caption ?? ""}
          className="max-w-full rounded border border-rule"
        />
        {caption ? (
          <p lang={primary ? primaryLang : secondaryLang} className="mt-2 text-sm text-ink-muted">
            {caption}
          </p>
        ) : null}
      </section>
    );
  }

  const shown = primary ?? secondary;
  if (!shown) return null;

  return (
    <section className="mb-4 rounded-lg border border-rule border-s-4 border-s-ink-muted bg-paper p-5">
      <h2 className="mb-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
        {stimulus.kind === "directions" ? labels.directions : labels.passage}
      </h2>
      <p
        lang={primary ? primaryLang : secondaryLang}
        className="leading-relaxed whitespace-pre-line"
      >
        {shown}
      </p>
      {primary && secondary ? (
        <p
          lang={secondaryLang}
          className="mt-3 border-s-2 border-rule ps-3 text-sm leading-relaxed whitespace-pre-line text-ink-muted"
        >
          {secondary}
        </p>
      ) : null}
    </section>
  );
}
