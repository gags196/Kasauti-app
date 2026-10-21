import { cookies } from "next/headers";

import { redirect } from "@/i18n/navigation";

/**
 * Where the learner's session lives on the web side.
 *
 * The API issues a bearer token; this app keeps it in an **httpOnly** cookie on its own
 * origin and forwards it as an `Authorization` header from server components. The token
 * is therefore never readable by client JavaScript, and the pages that need it stay
 * server components — which is the whole reason the API uses bearer tokens rather than
 * setting a cookie itself (a cookie on the API's origin would never reach :3000).
 *
 * Everything here is server-only. Importing it into a client component is a build error,
 * which is the guard we want: a token that reaches the browser bundle is a leaked token.
 */
export const SESSION_COOKIE = "kasauti_session";

/** A week, matching the token's own lifetime — a cookie that outlives its token just
 * produces confusing 401s instead of a clean signed-out state. */
export const SESSION_MAX_AGE = 60 * 60 * 24 * 7;

export async function getSessionToken(): Promise<string | null> {
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}

export async function setSessionToken(token: string): Promise<void> {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    // Off on localhost, on everywhere else. A Secure cookie is simply not stored over
    // plain http, which would make dev look like a broken login.
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
}

export async function clearSessionToken(): Promise<void> {
  (await cookies()).delete(SESSION_COOKIE);
}

/**
 * The token, or a redirect to the login form.
 *
 * next-intl's `redirect` is not typed as `never`, so every caller would otherwise have
 * to narrow `string | null` by hand right after a line that provably ends the request.
 * One helper, typed honestly, instead of that pattern repeated on every guarded page.
 */
export async function requireSessionToken(locale: string): Promise<string> {
  const token = await getSessionToken();
  if (token) return token;
  redirect({ href: "/account/login", locale });
  throw new Error("unreachable: redirect() does not return");
}
