import "katex/dist/katex.min.css";

import katex from "katex";

/**
 * Renders a stem that mixes prose with LaTeX. UPSC's Mathematics optional papers are
 * almost entirely notation — `$…$` inline, `$$ … $$` in display blocks — transcribed
 * verbatim into `text_en`/`text_hi`. KaTeX has no DOM dependency, so this renders on the
 * server with the rest of the page; the wrapper keeps the paper's own line breaks.
 *
 * `$$ … $$` is matched before `$ … $` so a display block is never mistaken for two
 * inline runs. Malformed math falls back to its literal source rather than throwing.
 */
const SEGMENT = /(\$\$[\s\S]+?\$\$|\$[^$]+?\$)/g;

function render(src: string, displayMode: boolean): string | null {
  try {
    return katex.renderToString(src, {
      displayMode,
      throwOnError: false,
      strict: false,
    });
  } catch {
    return null;
  }
}

export function MathText({ text }: { text: string }) {
  return (
    <>
      {text.split(SEGMENT).map((part, i) => {
        if (part.startsWith("$$") && part.endsWith("$$") && part.length > 4) {
          const html = render(part.slice(2, -2).trim(), true);
          return html ? (
            <span
              key={i}
              className="my-3 block overflow-x-auto"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          ) : (
            <span key={i}>{part}</span>
          );
        }
        if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
          const html = render(part.slice(1, -1).trim(), false);
          return html ? (
            <span key={i} dangerouslySetInnerHTML={{ __html: html }} />
          ) : (
            <span key={i}>{part}</span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}
