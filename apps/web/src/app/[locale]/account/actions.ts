"use server";

import { redirect } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { clearSessionToken, setSessionToken } from "@/lib/session";

/**
 * Sign-in, sign-up and sign-out, as server actions.
 *
 * The token never touches the browser: the form posts to the server, the server calls
 * the API, and the token goes straight into an httpOnly cookie. There is no client-side
 * auth state to get out of sync, and no token in a JS bundle to leak.
 *
 * Errors come back as a plain string rather than being thrown. A failed login is an
 * ordinary outcome of a form, not an exception, and rendering an error page for a typo'd
 * password would lose everything the learner had typed.
 */
export type FormState = { error: string | null };

const GENERIC_LOGIN_ERROR = "That email and password do not match an account.";

export async function signIn(
  _state: FormState,
  formData: FormData,
): Promise<FormState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  if (!email || !password) return { error: "Enter your email and password." };

  try {
    const token = await api.login(email, password);
    await setSessionToken(token);
  } catch (error) {
    if (error instanceof ApiError && error.status === 0) {
      return { error: "Cannot reach the Kasauti API. Is it running?" };
    }
    // Deliberately the same message for "no such account" and "wrong password": telling
    // the two apart turns the login form into a way to test whether an address is
    // registered here.
    return { error: GENERIC_LOGIN_ERROR };
  }
  redirect("/me");
}

export async function signUp(
  _state: FormState,
  formData: FormData,
): Promise<FormState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const name = String(formData.get("name") ?? "").trim();

  if (password.length < 8) {
    return { error: "Pick a password of at least 8 characters." };
  }

  try {
    await api.register({ email, password, name: name || undefined });
  } catch (error) {
    if (error instanceof ApiError && error.status === 400) {
      return { error: "An account with that email already exists." };
    }
    if (error instanceof ApiError && error.status === 422) {
      return { error: "That email address does not look valid." };
    }
    if (error instanceof ApiError && error.status === 0) {
      return { error: "Cannot reach the Kasauti API. Is it running?" };
    }
    return { error: "Could not create the account." };
  }

  // Registering signs you in — a second form immediately after the first is friction
  // with no security value, since the credentials were just accepted.
  try {
    await setSessionToken(await api.login(email, password));
  } catch {
    redirect("/account/login");
  }
  redirect("/me");
}

export async function signOut(): Promise<void> {
  await clearSessionToken();
  redirect("/");
}
