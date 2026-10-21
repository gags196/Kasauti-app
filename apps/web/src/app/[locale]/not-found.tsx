import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";

export default async function NotFound() {
  const t = await getTranslations("notFound");

  return (
    <div className="rounded-lg border border-rule bg-paper-raised p-8">
      <h1 className="text-xl font-medium">{t("title")}</h1>
      <p className="mt-2 text-ink-muted">{t("body")}</p>
      <Link href="/pyq" className="mt-6 inline-block text-accent hover:underline">
        {t("action")}
      </Link>
    </div>
  );
}
