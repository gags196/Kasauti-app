"""Score handwriting transcripts against hand-made reference transcripts.

Answers the question that gates the whole Mains evaluator: **does the reader find fewer of
a Hindi candidate's words than an English candidate's?** If it does, it will find fewer
rubric points in Hindi answers of equal quality, and shipping would penalise the cohort
with the least access to good human evaluation — the bilingual-parity invariant, applied
to handwriting.

    uv run python scripts/score_transcription.py \\
        --manifest content/benchmark_sets/handwriting_ocr_v1.yaml \\
        --candidates var/transcripts/standard/ --label claude-sonnet-5-standard \\
        --write-report

`--candidates` is a directory of `<sample_id>.json` HandwrittenAnswer files, one per sample
named in the manifest. References are plain UTF-8 text files, one per sample, read from the
directory the manifest names (kept out of the repo like every other labeled corpus).

Three things are reported, and the second is the launch gate:

1. CER and WER per language, pooled by totals rather than averaged over samples.
2. The **Hindi-minus-English gap**, with a bootstrap interval. The stated blocker is that
   the paired delta's interval excludes zero; this prints the interval rather than a
   verdict, because the threshold is a product decision and the number is not.
3. Whether the reader's own `uncertain_spans` land on its actual errors — which decides
   whether gating rubric verdicts on transcription confidence is worth building.
"""

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

# Windows consoles default to cp1252, which raises UnicodeEncodeError on the first
# Devanagari character printed. A tool whose whole purpose is Hindi text must not crash
# when asked to show any; replace what the terminal genuinely cannot render and carry on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from kasauti_api.domain.extraction.accuracy import (  # noqa: E402
    ErrorRate,
    character_error_rate,
    combine,
    flag_quality,
    word_error_rate,
)
from kasauti_api.domain.llm.schemas import HandwrittenAnswer  # noqa: E402

REPORT_DIR = REPO_ROOT / "benchmarks" / "reports" / "handwriting-ocr"
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_SEED = 20260901


@dataclass(frozen=True)
class SampleScore:
    sample_id: str
    language: str
    regime: str | None
    cer: ErrorRate
    wer: ErrorRate
    flags: object


def score_sample(sample: dict, reference: str, candidate: HandwrittenAnswer) -> SampleScore:
    return SampleScore(
        sample_id=sample["id"],
        language=sample["language"],
        regime=sample.get("regime"),
        cer=character_error_rate(reference, candidate.text),
        wer=word_error_rate(reference, candidate.text),
        flags=flag_quality(
            reference, candidate.text, [s.text for s in candidate.uncertain_spans]
        ),
    )


def pooled(scores: list[SampleScore], language: str | None = None) -> dict:
    chosen = [s for s in scores if language is None or s.language == language]
    return {
        "n": len(chosen),
        "cer": combine([s.cer for s in chosen]),
        "wer": combine([s.wer for s in chosen]),
    }


def bootstrap_gap(
    scores: list[SampleScore], metric: str = "cer"
) -> tuple[float, float, float] | None:
    """Hindi-minus-English CER, with a 95% percentile interval over resampled samples.

    Resampling is over *samples*, not characters: two pages by the same hand are not two
    independent observations of "can this be read", and pooling characters would report an
    interval far tighter than the evidence supports.
    """
    hindi = [s for s in scores if s.language == "hi"]
    english = [s for s in scores if s.language == "en"]
    if not hindi or not english:
        return None

    def pooled_rate(chosen: list[SampleScore]) -> float:
        return combine([getattr(s, metric) for s in chosen]).rate

    observed = pooled_rate(hindi) - pooled_rate(english)
    rng = random.Random(BOOTSTRAP_SEED)
    deltas = []
    for _ in range(BOOTSTRAP_SAMPLES):
        h = [rng.choice(hindi) for _ in hindi]
        e = [rng.choice(english) for _ in english]
        deltas.append(pooled_rate(h) - pooled_rate(e))
    deltas.sort()
    low = deltas[int(0.025 * len(deltas))]
    high = deltas[int(0.975 * len(deltas)) - 1]
    return observed, low, high


def render(scores: list[SampleScore], label: str, manifest: dict) -> str:
    overall = pooled(scores)
    by_language = {
        language: pooled(scores, language)
        for language in sorted({s.language for s in scores})
    }

    lines = [
        f"# Handwriting transcription accuracy — {label}",
        "",
        f"Set `{manifest['set_id']}` · {overall['n']} sample(s) · "
        f"scored {date.today().isoformat()}",
        "",
        "| Language | Samples | CER | WER |",
        "|---|---:|---:|---:|",
    ]
    for language, stats in by_language.items():
        lines.append(
            f"| {language} | {stats['n']} | {stats['cer'].rate:.2%} | "
            f"{stats['wer'].rate:.2%} |"
        )
    lines.append(
        f"| **all** | {overall['n']} | {overall['cer'].rate:.2%} | "
        f"{overall['wer'].rate:.2%} |"
    )
    lines.append("")

    gap = bootstrap_gap(scores)
    if gap is None:
        lines += [
            "> **No parity number: the set does not contain both languages.** A Hindi-only "
            "or English-only run cannot answer the question this measurement exists for.",
            "",
        ]
    else:
        observed, low, high = gap
        excludes_zero = low > 0 or high < 0
        lines += [
            "## Language parity",
            "",
            f"Hindi CER minus English CER: **{observed:+.2%}** "
            f"(95% CI {low:+.2%} to {high:+.2%}, bootstrapped over samples).",
            "",
            (
                "The interval **excludes zero**: on this evidence the reader is measurably "
                "worse in one language than the other, which is the stated launch blocker "
                "for Hindi."
                if excludes_zero
                else "The interval **includes zero**: this set does not show a language "
                "difference. Note that failing to show one is not the same as showing "
                "there is none — check the sample count before reading it as parity."
            ),
            "",
        ]

    total_flagged = sum(s.flags.flagged for s in scores)
    total_hits = sum(s.flags.flagged_wrong for s in scores)
    total_missed = sum(s.flags.unflagged_wrong for s in scores)
    lines += [
        "## Did the reader know when it was guessing?",
        "",
        f"{total_flagged} span(s) flagged as uncertain; {total_hits} of them contained a "
        f"word that is not in the reference. {total_missed} wrong word(s) were flagged by "
        "nothing.",
        "",
    ]
    if total_flagged:
        precision = total_hits / total_flagged
        recall = total_hits / (total_hits + total_missed) if (total_hits + total_missed) else 0
        lines += [
            f"Flag precision **{precision:.0%}**, flag recall **{recall:.0%}**.",
            "",
            "Recall is the number that matters: an error the reader knew it might be "
            "making is one the learner can fix on a confirmation screen. Low recall means "
            "gating rubric verdicts on transcription confidence would catch little and "
            "would mostly add false alarms.",
            "",
        ]
    else:
        lines += [
            "> **Nothing was flagged at all.** Either the pages were unambiguous or the "
            "reader is resolving doubt silently — the documented failure mode. Check a "
            "sample by hand before reading the CER above as good news.",
            "",
        ]

    lines += ["## Per sample", "", "| Sample | Lang | Regime | CER | WER | flagged |",
              "|---|:--:|---|---:|---:|---:|"]
    for s in sorted(scores, key=lambda s: (s.language, s.sample_id)):
        lines.append(
            f"| {s.sample_id} | {s.language} | {s.regime or '-'} | {s.cer.rate:.2%} | "
            f"{s.wer.rate:.2%} | {s.flags.flagged} |"
        )
    lines += [
        "",
        "## Reference caveat",
        "",
        *[f"- {limit.strip()}" for limit in manifest.get("known_limits", [])],
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True,
                        help="directory of <sample_id>.json HandwrittenAnswer files")
    parser.add_argument("--label", required=True, help="what produced the candidates")
    parser.add_argument("--references", type=Path,
                        help="override the reference directory named by the manifest")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()

    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("status") == "awaiting_source":
        raise SystemExit(
            f"{args.manifest} is still a collection spec, not a set: it has no samples "
            "yet. Fill in `samples:` and drop `status: awaiting_source` once the booklets "
            "and their reference transcripts exist."
        )

    reference_dir = args.references or Path(manifest["reference"]["local_dir"])
    if not reference_dir.is_dir():
        raise SystemExit(
            f"reference directory {reference_dir} not found. The gold transcripts are "
            "never committed (see .gitignore); point --references at your local copy."
        )

    scores: list[SampleScore] = []
    missing: list[str] = []
    for sample in manifest["samples"]:
        candidate_path = args.candidates / f"{sample['id']}.json"
        reference_path = reference_dir / f"{sample['id']}.txt"
        if not candidate_path.is_file() or not reference_path.is_file():
            missing.append(sample["id"])
            continue
        candidate = HandwrittenAnswer.model_validate_json(
            candidate_path.read_text(encoding="utf-8")
        )
        scores.append(
            score_sample(
                sample, reference_path.read_text(encoding="utf-8"), candidate
            )
        )

    if not scores:
        raise SystemExit("no sample had both a candidate and a reference")
    if missing:
        # Named, not silently dropped: a partial run that quietly scores the easy half of
        # a set reports a better number than the set actually earns.
        print(f"! skipped (no candidate or no reference): {', '.join(missing)}\n")

    report = render(scores, args.label, manifest)
    print(report)

    if args.write_report:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", args.label.lower()).strip("-")
        out = REPORT_DIR / f"{date.today().isoformat()}_{manifest['set_id']}_{slug}.md"
        out.write_text(report, encoding="utf-8")
        print(f"\nreport written: {out.relative_to(REPO_ROOT)}")
        summary = out.with_suffix(".json")
        summary.write_text(
            json.dumps(
                {
                    "label": args.label,
                    "set_id": manifest["set_id"],
                    "samples": [
                        {
                            "id": s.sample_id,
                            "language": s.language,
                            "cer": s.cer.rate,
                            "wer": s.wer.rate,
                            "flagged": s.flags.flagged,
                            "flagged_wrong": s.flags.flagged_wrong,
                            "unflagged_wrong": s.flags.unflagged_wrong,
                        }
                        for s in scores
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"summary written: {summary.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
