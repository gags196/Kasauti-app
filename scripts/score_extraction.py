"""Score a candidate extraction against a gold reference transcript.

Answers the question the pipeline cannot currently answer: *can the cheap tier actually
read a bilingual Devanagari scan?* Run a paper through the real API, then score the
result here against the reference in content/benchmark_sets/.

    uv run python scripts/score_extraction.py candidate.json \\
        --manifest content/benchmark_sets/prelims_gs1_2026_extraction.yaml \\
        --label claude-haiku-4-5

Reports per-question and per-option accuracy, separately for English and Hindi, because
a model can be strong on Latin and weak on Devanagari and a single blended number would
hide exactly the failure mode that matters here.
"""

import argparse
import hashlib
import re
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from kasauti_api.domain.llm.schemas import ScanExtraction  # noqa: E402
from kasauti_api.settings import get_settings  # noqa: E402
from kasauti_api.storage import download_bytes  # noqa: E402

REPORT_DIR = REPO_ROOT / "benchmarks" / "reports" / "extraction-accuracy"

# Text is compared after collapsing whitespace and stripping punctuation that scanning
# and transcription legitimately disagree on. Meaning-bearing characters are untouched.
_WS = re.compile(r"\s+")
_TRIM = re.compile(r"[‘’“”'\"`.,;:!?()\[\]{}–—-]")


def normalise(text: str | None) -> str:
    if not text:
        return ""
    return _WS.sub(" ", _TRIM.sub("", text)).strip().lower()


def similarity(a: str | None, b: str | None) -> float:
    na, nb = normalise(a), normalise(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def load_reference(manifest: dict) -> ScanExtraction:
    ref = manifest["reference"]
    data = download_bytes(get_settings().r2_bucket_scans, ref["key"])
    actual = hashlib.sha256(data).hexdigest()
    if actual != ref["sha256"]:
        raise SystemExit(
            f"Reference transcript hash mismatch.\n  expected {ref['sha256']}\n"
            f"  actual   {actual}\nThe reference has changed; scores would be meaningless."
        )
    return ScanExtraction.model_validate_json(data)


def score(reference: ScanExtraction, candidate: ScanExtraction) -> dict:
    ref_by_no = {q.question_number.strip(): q for q in reference.questions}
    cand_by_no = {q.question_number.strip(): q for q in candidate.questions}

    found = sorted(set(ref_by_no) & set(cand_by_no), key=lambda n: int(n) if n.isdigit() else 0)
    missing = sorted(set(ref_by_no) - set(cand_by_no))
    spurious = sorted(set(cand_by_no) - set(ref_by_no))

    per_question = []
    for number in found:
        r, c = ref_by_no[number], cand_by_no[number]
        ref_labels = {o.label.strip().upper() for o in r.options}
        cand_labels = {o.label.strip().upper() for o in c.options}
        cand_opts = {o.label.strip().upper(): o for o in c.options}

        opt_en, opt_hi = [], []
        for option in r.options:
            match = cand_opts.get(option.label.strip().upper())
            opt_en.append(similarity(option.text_en, match.text_en if match else None))
            opt_hi.append(similarity(option.text_hi, match.text_hi if match else None))

        per_question.append({
            "question_number": number,
            "text_en": similarity(r.text_en, c.text_en),
            "text_hi": similarity(r.text_hi, c.text_hi),
            "option_labels_exact": ref_labels == cand_labels,
            "option_en": sum(opt_en) / len(opt_en) if opt_en else 1.0,
            "option_hi": sum(opt_hi) / len(opt_hi) if opt_hi else 1.0,
            # Extraction must never assert correctness — the answer key does that.
            "guessed_correctness": any(
                getattr(o, "is_correct", None) is not None for o in c.options
            ),
        })

    def mean(field: str) -> float:
        values = [q[field] for q in per_question]
        return sum(values) / len(values) if values else 0.0

    return {
        "reference_questions": len(ref_by_no),
        "candidate_questions": len(cand_by_no),
        "matched": len(found),
        "missing": missing,
        "spurious": spurious,
        "recall": len(found) / len(ref_by_no) if ref_by_no else 0.0,
        "text_en": mean("text_en"),
        "text_hi": mean("text_hi"),
        "option_en": mean("option_en"),
        "option_hi": mean("option_hi"),
        "option_labels_exact": (
            sum(q["option_labels_exact"] for q in per_question) / len(per_question)
            if per_question else 0.0
        ),
        "guessed_correctness": any(q["guessed_correctness"] for q in per_question),
        "per_question": per_question,
    }


def render(result: dict, label: str, manifest: dict) -> str:
    lines = [
        f"# Extraction accuracy — {label}",
        "",
        f"Set `{manifest['set_id']}` · scored {date.today().isoformat()}",
        "",
        "| Metric | Score |",
        "|---|---:|",
        f"| Questions found | {result['matched']} / {result['reference_questions']} "
        f"({result['recall']:.0%}) |",
        f"| Question text — English | {result['text_en']:.1%} |",
        f"| Question text — **Hindi** | {result['text_hi']:.1%} |",
        f"| Option text — English | {result['option_en']:.1%} |",
        f"| Option text — **Hindi** | {result['option_hi']:.1%} |",
        f"| Option labels exactly right | {result['option_labels_exact']:.0%} |",
        "",
    ]
    if result["guessed_correctness"]:
        lines += [
            "> **FAIL: the candidate asserted `is_correct` on some options.** Correctness "
            "may only come from an official answer key. This is a correctness violation, "
            "not a quality score.",
            "",
        ]
    if result["missing"]:
        lines += [f"Missing questions: {', '.join(result['missing'])}", ""]
    if result["spurious"]:
        lines += [f"Questions not in the reference: {', '.join(result['spurious'])}", ""]

    gap = result["text_en"] - result["text_hi"]
    lines += [
        f"English-minus-Hindi gap: **{gap:+.1%}**. A large positive gap means the model "
        "reads Latin far better than Devanagari — the failure mode that matters most for "
        "a bilingual product, and the one a blended average would hide.",
        "",
        "## Per question",
        "",
        "| Q | text EN | text HI | opts EN | opts HI | labels |",
        "|---|---:|---:|---:|---:|:--:|",
    ]
    for q in result["per_question"]:
        lines.append(
            f"| {q['question_number']} | {q['text_en']:.1%} | {q['text_hi']:.1%} | "
            f"{q['option_en']:.1%} | {q['option_hi']:.1%} | "
            f"{'ok' if q['option_labels_exact'] else 'MISMATCH'} |"
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
    parser.add_argument("candidate", type=Path, help="ScanExtraction JSON to score")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--label", required=True, help="what produced the candidate")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()

    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    reference = load_reference(manifest)
    candidate = ScanExtraction.model_validate_json(
        args.candidate.read_text(encoding="utf-8")
    )

    result = score(reference, candidate)
    report = render(result, args.label, manifest)
    print(report)

    if args.write_report:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", args.label.lower()).strip("-")
        out = REPORT_DIR / f"{date.today().isoformat()}_{manifest['set_id']}_{slug}.md"
        out.write_text(report, encoding="utf-8")
        print(f"\nreport written: {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
