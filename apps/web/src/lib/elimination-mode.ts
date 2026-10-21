/**
 * Elimination Lab mode lives in a cookie so the *server* decides whether to fetch and
 * render the lab at all.
 *
 * This constant deliberately sits in its own module rather than beside the toggle
 * component. A `"use client"` module's exports reach a server component as client
 * *references*, not as values, so `cookies().get(NAME)` there silently reads a proxy
 * object, finds nothing, and reports the mode as off — with no error anywhere. The bug
 * looks exactly like a user who never clicked the button.
 */
export const ELIMINATION_COOKIE = "kasauti_elimination";

export function isEliminationEnabled(value: string | undefined): boolean {
  return value === "1";
}
