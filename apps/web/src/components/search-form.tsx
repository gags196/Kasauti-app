import { getTranslations } from "next-intl/server";

/**
 * A plain GET form: the query lives in the URL, so results are shareable,
 * bookmarkable and survive a locale switch. Defaults come from the page's own
 * searchParams, which keeps this a server component with no client state.
 */
export async function SearchForm({
  defaults,
}: {
  defaults: { q?: string; from?: string; to?: string };
}) {
  const t = await getTranslations("pyq");

  return (
    <form className="mt-6 flex flex-wrap items-end gap-3">
      <label className="min-w-56 flex-1">
        <span className="mb-1 block text-sm text-ink-muted">{t("searchLabel")}</span>
        <input
          type="search"
          name="q"
          defaultValue={defaults.q ?? ""}
          placeholder={t("searchPlaceholder")}
          minLength={2}
          required
          className="w-full rounded-lg border border-rule bg-paper-raised px-3 py-2 outline-none focus:border-ink"
        />
      </label>
      <label className="w-28">
        <span className="mb-1 block text-sm text-ink-muted">{t("yearFrom")}</span>
        <input
          type="number"
          name="from"
          inputMode="numeric"
          defaultValue={defaults.from ?? ""}
          min={1979}
          max={2100}
          className="w-full rounded-lg border border-rule bg-paper-raised px-3 py-2 tabular-nums outline-none focus:border-ink"
        />
      </label>
      <label className="w-28">
        <span className="mb-1 block text-sm text-ink-muted">{t("yearTo")}</span>
        <input
          type="number"
          name="to"
          inputMode="numeric"
          defaultValue={defaults.to ?? ""}
          min={1979}
          max={2100}
          className="w-full rounded-lg border border-rule bg-paper-raised px-3 py-2 tabular-nums outline-none focus:border-ink"
        />
      </label>
      <button
        type="submit"
        className="rounded-lg bg-accent px-4 py-2 font-medium text-paper-raised"
      >
        {t("searchAction")}
      </button>
    </form>
  );
}
