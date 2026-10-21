import { getTranslations, setRequestLocale } from "next-intl/server";

import { AuthForm } from "@/components/auth-form";
import { Link, redirect } from "@/i18n/navigation";
import { getSessionToken } from "@/lib/session";

import { signUp } from "../actions";

export default async function RegisterPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("account");

  // Already signed in: send them to their own page rather than showing a form that
  // would replace one valid session with another.
  if (await getSessionToken()) redirect({ href: "/me", locale });

  return (
    <article className="max-w-lg">
      <h1 className="text-2xl font-semibold tracking-tight">{t("registerTitle")}</h1>
      <p className="mt-2 text-ink-muted">{t("registerLede")}</p>

      <AuthForm
        action={signUp}
        mode="register"
        labels={{
          email: t("email"),
          password: t("password"),
          name: t("name"),
          namePlaceholder: t("namePlaceholder"),
          submit: t("registerAction"),
          pending: t("pending"),
          passwordHint: t("passwordHint"),
        }}
      />

      <p className="mt-6 text-sm text-ink-muted">
        {t("haveAccount")}{" "}
        <Link href="/account/login" className="text-accent hover:underline">
          {t("loginAction")}
        </Link>
      </p>
    </article>
  );
}
