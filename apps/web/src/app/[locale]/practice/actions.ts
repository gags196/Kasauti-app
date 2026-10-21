"use server";

import { redirect } from "next/navigation";

import { ApiError, api, type PracticeMode } from "@/lib/api";
import { getSessionToken } from "@/lib/session";

/**
 * Server actions for sitting a paper.
 *
 * The exam UI is a client component, but every call it makes lands here first so the
 * session token stays server-side. The client knows a session id and nothing else.
 */
async function requireToken(): Promise<string> {
  const token = await getSessionToken();
  if (!token) redirect("/account/login");
  return token;
}

export async function startPractice(formData: FormData): Promise<void> {
  const token = await requireToken();
  const mode = String(formData.get("mode") ?? "full_mock") as PracticeMode;
  const paperCode = String(formData.get("paper_code") ?? "");
  const yearValue = String(formData.get("year") ?? "");
  const topicPath = String(formData.get("topic_path") ?? "");
  const countValue = String(formData.get("count") ?? "");

  let sessionId: string;
  try {
    const session = await api.startSession(token, {
      mode,
      paper_code: paperCode || undefined,
      year: yearValue ? Number(yearValue) : undefined,
      topic_path: topicPath || undefined,
      count: countValue ? Number(countValue) : undefined,
    });
    sessionId = session.id;
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      // Not enough keyed questions for that selection — the corpus is the limit, and
      // saying so beats a paper with four questions on it.
      redirect("/practice?error=not-enough");
    }
    throw error;
  }
  redirect(`/practice/${sessionId}`);
}

export async function saveAnswer(
  sessionId: string,
  questionId: number,
  label: string | null,
  seconds: number,
): Promise<void> {
  const token = await requireToken();
  await api.saveAnswer(token, sessionId, questionId, {
    selected_label: label,
    seconds_taken: seconds,
  });
}

export async function submitPractice(sessionId: string): Promise<void> {
  const token = await requireToken();
  await api.submitSession(token, sessionId);
  redirect(`/practice/${sessionId}`);
}
