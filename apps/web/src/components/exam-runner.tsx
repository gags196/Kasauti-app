"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { PracticeQuestion } from "@/lib/api";
import { StimulusBlock } from "./stimulus";

/**
 * Sitting a paper: one question at a time, a palette to jump around, a clock, and a
 * submit that cannot be taken back.
 *
 * This is the largest client component in the app and it earns that — a timed exam is
 * interaction, not content. Three decisions shape it, and each mirrors the real OMR
 * sheet rather than a quiz app:
 *
 * **Answers save as they are made, not on submit.** A learner who loses connectivity
 * ninety minutes in must not lose ninety minutes. Each save is an idempotent PUT, so a
 * retry is free and out-of-order responses cannot resurrect an old answer.
 *
 * **Clearing an answer is a first-class action.** Under UPSC's negative marking a blank
 * scores zero and a wrong answer costs a third of a mark, so "I no longer want to guess
 * this" is a real decision the interface has to support.
 *
 * **The clock never submits for you.** It counts down and turns red, and it keeps
 * counting past zero into overtime. Auto-submitting on a browser tab that was throttled
 * in the background would end someone's paper for them because of a timer they could not
 * see; the total time sat is recorded either way.
 */
type Answers = Record<number, string | null>;

export function ExamRunner({
  sessionId,
  questions,
  durationSeconds,
  startedAt,
  locale,
  labels,
  onSave,
  onSubmit,
}: {
  sessionId: string;
  questions: PracticeQuestion[];
  durationSeconds: number | null;
  startedAt: string;
  locale: string;
  labels: Record<string, string>;
  onSave: (
    sessionId: string,
    questionId: number,
    label: string | null,
    seconds: number,
  ) => Promise<void>;
  onSubmit: (sessionId: string) => Promise<void>;
}) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Answers>(() =>
    Object.fromEntries(questions.map((q) => [q.id, q.selected_label ?? null])),
  );
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const questionEnteredAt = useRef(Date.now());

  const started = useMemo(() => new Date(startedAt).getTime(), [startedAt]);
  useEffect(() => {
    const tick = () => setElapsed(Math.floor((Date.now() - started) / 1000));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [started]);

  const question = questions[index];
  const remaining = durationSeconds === null ? null : durationSeconds - elapsed;
  const answeredCount = Object.values(answers).filter(Boolean).length;

  const save = useCallback(
    async (questionId: number, label: string | null) => {
      const seconds = Math.round((Date.now() - questionEnteredAt.current) / 1000);
      setAnswers((prev) => ({ ...prev, [questionId]: label }));
      setSaving(true);
      try {
        await onSave(sessionId, questionId, label, seconds);
      } finally {
        setSaving(false);
      }
    },
    [onSave, sessionId],
  );

  const go = useCallback(
    (next: number) => {
      if (next < 0 || next >= questions.length) return;
      questionEnteredAt.current = Date.now();
      setIndex(next);
    },
    [questions.length],
  );

  // Keyboard: A-D to answer, arrows to move. An aspirant doing 100 questions should not
  // have to reach for a mouse a hundred times.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.target instanceof HTMLInputElement) return;
      const key = event.key.toUpperCase();
      if (["A", "B", "C", "D"].includes(key)) {
        const option = question?.options.find((o) => o.label === key);
        if (option) void save(question.id, key);
      } else if (event.key === "ArrowRight") go(index + 1);
      else if (event.key === "ArrowLeft") go(index - 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [question, index, go, save]);

  if (!question) return null;

  const primary = locale === "hi" ? question.text_hi : question.text_en;
  const secondary = locale === "hi" ? question.text_en : question.text_hi;
  const selected = answers[question.id] ?? null;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_16rem]">
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm text-ink-muted">
            {labels.questionOf
              .replace("{index}", String(index + 1))
              .replace("{total}", String(questions.length))}
          </p>
          <p
            className={`text-sm tabular-nums ${
              remaining !== null && remaining < 0
                ? "text-caution"
                : remaining !== null && remaining < 300
                  ? "text-accent"
                  : "text-ink-muted"
            }`}
          >
            {remaining === null
              ? formatClock(elapsed)
              : remaining < 0
                ? `${labels.overtime} ${formatClock(-remaining)}`
                : formatClock(remaining)}
          </p>
        </div>

        <StimulusBlock
          stimulus={question.stimulus}
          locale={locale}
          labels={{
            passage: labels.passage,
            directions: labels.directions,
            figure: labels.figure,
          }}
        />

        <div className="rounded-lg border border-rule bg-paper-raised p-5">
          <p lang={locale} className="text-lg leading-relaxed whitespace-pre-line">
            {primary}
          </p>
          {secondary ? (
            <p
              lang={locale === "hi" ? "en" : "hi"}
              className="mt-3 border-s-2 border-rule ps-3 text-sm whitespace-pre-line text-ink-muted"
            >
              {secondary}
            </p>
          ) : null}
        </div>

        <ol className="mt-4 grid gap-2">
          {question.options.map((option) => {
            const chosen = selected === option.label;
            return (
              <li key={option.label}>
                <button
                  type="button"
                  onClick={() => void save(question.id, chosen ? null : option.label)}
                  aria-pressed={chosen}
                  className={`flex w-full gap-3 rounded-lg border p-4 text-start transition-colors ${
                    chosen
                      ? "border-accent bg-accent-soft"
                      : "border-rule bg-paper-raised hover:border-ink"
                  }`}
                >
                  <span className="font-medium tabular-nums">{option.label}.</span>
                  <span className="min-w-0 flex-1">
                    <span lang={locale} className="block">
                      {locale === "hi" ? option.text_hi : option.text_en}
                    </span>
                    <span
                      lang={locale === "hi" ? "en" : "hi"}
                      className="mt-1 block text-sm text-ink-muted"
                    >
                      {locale === "hi" ? option.text_en : option.text_hi}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => go(index - 1)}
            disabled={index === 0}
            className="rounded-full border border-rule px-4 py-1.5 text-sm disabled:opacity-40"
          >
            {labels.previous}
          </button>
          <button
            type="button"
            onClick={() => go(index + 1)}
            disabled={index === questions.length - 1}
            className="rounded-full border border-rule px-4 py-1.5 text-sm disabled:opacity-40"
          >
            {labels.next}
          </button>
          {selected ? (
            <button
              type="button"
              onClick={() => void save(question.id, null)}
              className="rounded-full border border-rule px-4 py-1.5 text-sm text-ink-muted hover:text-ink"
            >
              {labels.clear}
            </button>
          ) : null}
          <span className="text-xs text-ink-muted">{saving ? labels.saving : ""}</span>
        </div>
      </div>

      <aside className="lg:sticky lg:top-6 lg:self-start">
        <p className="text-sm text-ink-muted">
          {labels.answeredOf
            .replace("{answered}", String(answeredCount))
            .replace("{total}", String(questions.length))}
        </p>
        <ol className="mt-3 flex flex-wrap gap-1.5">
          {questions.map((item, itemIndex) => {
            const done = Boolean(answers[item.id]);
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => go(itemIndex)}
                  aria-current={itemIndex === index}
                  className={`size-8 rounded text-xs tabular-nums ${
                    itemIndex === index
                      ? "border-2 border-ink"
                      : done
                        ? "bg-accent-soft text-accent"
                        : "border border-rule text-ink-muted"
                  }`}
                >
                  {itemIndex + 1}
                </button>
              </li>
            );
          })}
        </ol>

        <button
          type="button"
          disabled={submitting}
          onClick={() => {
            // No dialog for a paper in progress, one for an incomplete paper: the
            // blanks a learner left on purpose are worth confirming, and an accidental
            // submit halfway through is unrecoverable.
            const unanswered = questions.length - answeredCount;
            if (
              unanswered > 0 &&
              !window.confirm(
                labels.confirmSubmit.replace("{count}", String(unanswered)),
              )
            ) {
              return;
            }
            setSubmitting(true);
            void onSubmit(sessionId);
          }}
          className="mt-6 w-full rounded-full border border-accent bg-accent-soft px-4 py-2 text-sm text-accent disabled:opacity-60"
        >
          {submitting ? labels.submitting : labels.submit}
        </button>
        <p className="mt-2 text-xs text-ink-muted">{labels.negativeMarking}</p>
      </aside>
    </div>
  );
}

function formatClock(seconds: number): string {
  const safe = Math.max(0, seconds);
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = safe % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}
