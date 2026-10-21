import { getTranslations } from "next-intl/server";

import type { ApiError } from "@/lib/api";

/** A dead backend is the common failure in dev — say so, and say how to fix it. */
export async function ApiErrorNotice({ error }: { error: ApiError }) {
  const t = await getTranslations("error");
  const unreachable = error.status === 0;

  return (
    <div className="rounded-lg border border-rule bg-paper-raised p-6">
      <p className="font-medium">{unreachable ? t("apiDown") : t("generic")}</p>
      <p className="mt-2 text-sm text-ink-muted">
        {unreachable ? t("apiDownHint") : `${error.status} · ${error.path}`}
      </p>
    </div>
  );
}
