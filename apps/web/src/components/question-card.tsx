import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import type { Question } from "@/lib/api";
import { Bilingual } from "./bilingual";

function topicLabel(path: string) {
  // ltree labels use underscores; read them back as words.
  return path.split(".").pop()?.replaceAll("_", " ") ?? path;
}

export async function QuestionCard({
  question,
  score,
}: {
  question: Question;
  score?: number;
}) {
  const t = await getTranslations("pyq");

  return (
    <article className="rounded-lg border border-rule bg-paper-raised p-5">
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
        <span className="font-medium text-ink">{question.year}</span>
        <span>Q{question.question_number}</span>
        {question.marks ? <span>{question.marks} marks</span> : null}
        {score !== undefined ? (
          <span className="ms-auto">{t("score", { score: score.toFixed(2) })}</span>
        ) : null}
      </div>

      <Link href={`/pyq/${question.id}`} className="block hover:underline">
        <Bilingual en={question.text_en} hi={question.text_hi} />
      </Link>

      {question.math_latex ? (
        <pre className="latex mt-3 rounded border border-rule p-3 text-ink-muted">
          {question.math_latex}
        </pre>
      ) : null}

      {question.topic_paths.length > 0 ? (
        <ul className="mt-4 flex flex-wrap gap-2">
          {question.topic_paths.map((path) => (
            <li
              key={path}
              className="rounded-full border border-rule px-2.5 py-0.5 text-xs text-ink-muted"
            >
              {topicLabel(path)}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}
