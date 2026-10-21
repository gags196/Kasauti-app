"use client";

import { useActionState } from "react";

import type { FormState } from "@/app/[locale]/account/actions";

/**
 * The sign-in / sign-up form.
 *
 * A client component only because it needs `useActionState` to render the server's error
 * beside the fields the learner already filled in. The action itself runs on the server
 * and the token never enters this bundle — see `lib/session.ts`.
 */
export function AuthForm({
  action,
  mode,
  labels,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  mode: "login" | "register";
  labels: {
    email: string;
    password: string;
    name: string;
    namePlaceholder: string;
    submit: string;
    pending: string;
    passwordHint: string;
  };
}) {
  const [state, formAction, pending] = useActionState<FormState, FormData>(action, {
    error: null,
  });

  return (
    <form action={formAction} className="mt-6 grid max-w-sm gap-4">
      {mode === "register" ? (
        <label className="grid gap-1.5 text-sm">
          <span className="text-ink-muted">{labels.name}</span>
          <input
            name="name"
            autoComplete="name"
            placeholder={labels.namePlaceholder}
            className="rounded-lg border border-rule bg-paper-raised px-3 py-2 outline-none focus:border-ink"
          />
        </label>
      ) : null}

      <label className="grid gap-1.5 text-sm">
        <span className="text-ink-muted">{labels.email}</span>
        <input
          name="email"
          type="email"
          required
          autoComplete="email"
          className="rounded-lg border border-rule bg-paper-raised px-3 py-2 outline-none focus:border-ink"
        />
      </label>

      <label className="grid gap-1.5 text-sm">
        <span className="text-ink-muted">{labels.password}</span>
        <input
          name="password"
          type="password"
          required
          minLength={8}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          className="rounded-lg border border-rule bg-paper-raised px-3 py-2 outline-none focus:border-ink"
        />
        {mode === "register" ? (
          <span className="text-xs text-ink-muted">{labels.passwordHint}</span>
        ) : null}
      </label>

      {state.error ? (
        <p role="alert" className="text-sm text-caution">
          {state.error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={pending}
        className="justify-self-start rounded-full border border-accent bg-accent-soft px-4 py-2 text-sm text-accent disabled:opacity-60"
      >
        {pending ? labels.pending : labels.submit}
      </button>
    </form>
  );
}
