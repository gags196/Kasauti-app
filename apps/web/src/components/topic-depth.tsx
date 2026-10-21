import { getTranslations } from "next-intl/server";

import { Legend, StackedBar, YearBars, bucketLabel } from "@/components/bars";
import { Link } from "@/i18n/navigation";
import type { DepthProfile, Projection } from "@/lib/api";

/**
 * The founder's "depth" feature: how far a topic has actually been probed, which of its
 * branches carry the weight, which have never been touched — and what comparable topics
 * suggest about it.
 *
 * Two things are shown that a normal analytics panel would hide, and both are the point:
 *
 * - **Branches with zero questions are listed.** Hiding them makes a topic look
 *   uniformly covered and deletes the only genuinely actionable part of the view.
 * - **Gap years are listed.** A topic asked in eleven of fourteen years is a different
 *   object from one asked every year, and an average hides the difference.
 *
 * The projection is deterministic — the peers' *measured* mix, never a model's guess —
 * so what a learner reads is "topics like this one are examined this way", which the
 * corpus supports, rather than "this will be asked", which it does not.
 */
export async function TopicDepth({
  profile,
  projection,
}: {
  profile: DepthProfile;
  projection: Projection | null;
}) {
  const t = await getTranslations("depth");
  const archetypes = Object.entries(profile.archetype_mix);
  const archetypeTotal = archetypes.reduce((sum, [, n]) => sum + n, 0) || 1;
  const untouched = profile.branches.filter((b) => b.subtree_count === 0);
  const covered = profile.branches.filter((b) => b.subtree_count > 0);

  return (
    <section className="grid gap-8">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">{t("title")}</h2>
        <p className="mt-2 max-w-2xl text-ink-muted">{t("lede")}</p>
      </div>

      <dl className="flex flex-wrap gap-x-10 gap-y-4 text-sm">
        <div>
          <dt className="text-ink-muted">{t("questions")}</dt>
          <dd className="text-lg tabular-nums">{profile.question_count}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">{t("probeStatus")}</dt>
          <dd className="text-lg">{t(`status.${profile.probe_status}`)}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">{t("asked")}</dt>
          <dd className="text-lg tabular-nums">
            {profile.first_year && profile.latest_year
              ? `${profile.first_year}–${profile.latest_year}`
              : "—"}
          </dd>
        </div>
        {profile.recurrence_rate !== null ? (
          <div>
            <dt className="text-ink-muted">{t("recurrence")}</dt>
            <dd className="text-lg tabular-nums">
              {Math.round(profile.recurrence_rate * 100)}%
            </dd>
          </div>
        ) : null}
      </dl>

      {profile.year_counts.length > 0 ? (
        <div>
          <h3 className="text-sm font-medium text-ink-muted">{t("perYear")}</h3>
          <div className="mt-3 rounded-lg border border-rule bg-paper-raised p-4">
            <YearBars points={profile.year_counts} emptyLabel={t("notAsked")} />
          </div>
          {profile.gap_years.length > 0 ? (
            <p className="mt-2 text-xs text-ink-muted">
              {t("gapYears", { years: profile.gap_years.join(", ") })}
            </p>
          ) : null}
        </div>
      ) : null}

      {archetypes.length > 0 ? (
        <div>
          <h3 className="text-sm font-medium text-ink-muted">{t("optionShapes")}</h3>
          <div className="mt-3">
            <StackedBar
              height="1rem"
              segments={archetypes.map(([name, count], index) => ({
                key: name,
                share: count / archetypeTotal,
                colorIndex: index,
                label: bucketLabel(name),
              }))}
            />
            <Legend
              items={archetypes.map(([name], index) => ({
                key: name,
                label: bucketLabel(name),
                colorIndex: index,
              }))}
            />
          </div>
          {/* The cognitive half of this profile needs the classification pass. Saying so
              is better than an empty chart that reads as "nothing to report". */}
          {profile.profiled_count === 0 ? (
            <p className="mt-3 text-xs text-ink-muted">{t("notClassified")}</p>
          ) : null}
        </div>
      ) : null}

      {covered.length > 0 || untouched.length > 0 ? (
        <div>
          <h3 className="text-sm font-medium text-ink-muted">{t("branches")}</h3>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[32rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-rule text-ink-muted">
                  <th className="py-2 pe-4 text-start font-medium">{t("colBranch")}</th>
                  <th className="py-2 pe-4 text-end font-medium">{t("colCount")}</th>
                  <th className="py-2 pe-4 text-end font-medium">{t("colLast")}</th>
                  <th className="py-2 text-start font-medium">{t("colStatus")}</th>
                </tr>
              </thead>
              <tbody>
                {[...covered, ...untouched].map((branch) => (
                  <tr key={branch.topic_id} className="border-b border-rule">
                    <td className="py-2 pe-4">
                      <Link
                        href={`/topics/${branch.topic_id}`}
                        className="hover:text-accent"
                      >
                        {branch.name_en}
                      </Link>
                    </td>
                    <td className="py-2 pe-4 text-end tabular-nums">
                      {branch.subtree_count}
                    </td>
                    <td className="py-2 pe-4 text-end tabular-nums text-ink-muted">
                      {branch.latest_year ?? "—"}
                    </td>
                    <td
                      className={`py-2 ${
                        branch.subtree_count === 0 ? "text-caution" : "text-ink-muted"
                      }`}
                    >
                      {t(`status.${branch.probe_status}`)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {profile.repeats.length > 0 ? (
        <div>
          <h3 className="text-sm font-medium text-ink-muted">{t("repeats")}</h3>
          <p className="mt-1 text-xs text-ink-muted">{t("repeatsNote")}</p>
          <ul className="mt-3 grid gap-3">
            {profile.repeats.map((pair) => (
              <li
                key={`${pair.earlier_id}-${pair.later_id}`}
                className="rounded-lg border border-rule bg-paper-raised p-4 text-sm"
              >
                <p className="text-xs text-ink-muted">
                  {t("similarity", {
                    value: Math.round(pair.similarity * 100),
                    apart: pair.years_apart,
                  })}
                </p>
                <div className="mt-2 grid gap-2">
                  <Link href={`/pyq/${pair.earlier_id}`} className="hover:text-accent">
                    <span className="tabular-nums text-ink-muted">
                      {pair.earlier_year}
                    </span>{" "}
                    {pair.earlier_text?.slice(0, 160)}
                  </Link>
                  <Link href={`/pyq/${pair.later_id}`} className="hover:text-accent">
                    <span className="tabular-nums text-ink-muted">{pair.later_year}</span>{" "}
                    {pair.later_text?.slice(0, 160)}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {projection ? (
        <div className="rounded-lg border border-rule bg-paper-raised p-5">
          <h3 className="text-lg font-medium">{t("projectionTitle")}</h3>
          <p className="mt-1 max-w-2xl text-sm text-ink-muted">{t("projectionLede")}</p>

          {projection.peers.length > 0 ? (
            <>
              <ul className="mt-4 flex flex-wrap gap-2">
                {projection.peers.map((peer) => (
                  <li key={peer.topic_id}>
                    <Link
                      href={`/topics/${peer.topic_id}`}
                      className="inline-block rounded-full border border-rule px-3 py-1 text-sm hover:border-ink"
                    >
                      {peer.name_en}{" "}
                      <span className="tabular-nums text-ink-muted">
                        {peer.subtree_count}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>

              {projection.expected_questions_per_year !== null ? (
                <p className="mt-4 text-sm">
                  {t("expectedVolume", {
                    rate: projection.expected_questions_per_year.toFixed(1),
                  })}
                </p>
              ) : null}

              {projection.untouched_branches.length > 0 ? (
                <p className="mt-2 text-sm">
                  {t("untouched", {
                    count: projection.untouched_branches.length,
                    names: projection.untouched_branches
                      .slice(0, 4)
                      .map((b) => b.name_en)
                      .join(", "),
                  })}
                </p>
              ) : null}
            </>
          ) : null}

          {/* Always present, by construction: a projection from three peers is not the
              same object as one from thirty, and the difference travels with it. */}
          <p className="mt-4 text-xs text-ink-muted">{projection.confidence_note}</p>
        </div>
      ) : null}
    </section>
  );
}
