# Worked example: the evaluator design run end-to-end, by hand

*2026-09-01. One real answer, one real rubric, one real judging prompt, judged manually through the
same contract the automated evaluator will use (`ContentPointBatch`). No API key was involved —
this is the manual-queue path. The point is to find out whether the design produces useful output
before any of it is automated.*

**Inputs**
- Question: GS1 2024 Q2 — *"Evaluate the role of subsidiary alliance policy in turning 'the British
  Empire in India' into 'the British Empire of India'."* (10 marks, 150 words)
- Answer: Shakti Dubey (AIR 1, CSE 2024), transcribed from a Vajiram & Ravi test-series booklet —
  see `2026-09-01_ground-truth-and-ocr-probe.md`.
- Rubric: `content/rubrics/gs1/gs1-2024-q2-subsidiary-alliance-v1.yaml`
- Prompt: `content/prompts/evaluation/gs_content_point_v1.md`

## Verdicts

| Point | Present | Evidence quoted from the answer |
|---|---|---|
| `attribute-and-define` | ✅ | "This policy was put forward by Richard Wellesley" |
| `feature-no-own-army` | ✅ | "could not have an army of their own" |
| `feature-troops-at-state-cost` | ✅ | "They had to station British army in their territory, which were to be maintained by the states themselves" |
| `feature-no-foreign-policy` | ✅ | "The state could not have any independent foreign policy" |
| `feature-no-european-relations` | ✅ | "They could not engage with Portuguese or French without permission of British" |
| `feature-british-resident` | ✅ | "One British official was to be stationed in their court" |
| `feature-no-europeans-employed` | ❌ | — |
| `names-annexed-states` | ✅ | "Hyderabad, Bha?tpur, Satara, Jaunpur ... fell prey to this British policy of paramountcy" |
| `links-doctrine-of-lapse` | ✅ | "further extended by \"Doctrine of Lapse\" under Dalhousie" |
| `addresses-in-vs-of` | ⚠️ partial | "Advent of British in India as a trading company & their withdrawal as a colonial power" |

Group `treaty-features`: **5 of 6 hit, against an `expect_k` of 3.**

## What the run actually taught us

**1. The one genuinely useful piece of feedback is the partial, and it is on an AIR-1 answer.**
`addresses-in-vs-of` asks whether the candidate engages the question's own framing — the shift from
a trading presence *in* India to sovereign paramountcy *of* India. The answer gestures at that arc in
its opening ("trading company … withdrawal as a colonial power") but its conclusion returns only to
"establishing the British Empire", never to the distinction the question is built on. The candidate
front-loads six treaty features — two more than needed — and under-serves the analytical demand.

That is a real, specific, actionable observation about a topper's answer, and it is exactly the class
of feedback no question bank or model-answer PDF gives. It is also the strongest evidence so far that
the reframe was right: **a predicted mark would have said "8/10" and taught nobody anything.**

**2. `expect_k` earns its place.** Five of six features hit, three expected. Without the group
construct this reads as "5/6 — nearly complete". With it, it reads as "you spent marks you had
already earned." Over-coverage of the easy half is a known way to lose marks on a 150-word answer,
and the rubric can now see it.

**3. The OCR ambiguity did not propagate — by luck, and the design should not rely on luck.**
`names-annexed-states` needs two correct states. Hyderabad and Satara are unambiguous, so the verdict
holds regardless of the smudged token. But two of the four names are doubtful: the fourth reads
"Jaunpur", which was not a princely state annexed by this route (Jhansi or Nagpur is far more
likely), and the second is the Bharatpur/"Bhagatpur" ambiguity flagged in the OCR probe. Under the
prompt's own rule both should have been listed in `illegible_spans` rather than silently read.

The lesson generalises: **a rubric point satisfied by "any two of a set" is robust to transcription
noise; a point satisfied by one specific token is not.** Where a rubric hangs on a single name, date
or figure, the OCR confidence for that span must gate the verdict. That is a design constraint worth
carrying into the engine, not a one-off observation.

**4. Nothing here required a score, and nothing was tempted to invent one.** The contract has no
field for a mark, so the failure mode of "produce a plausible number" is structurally unavailable
rather than merely discouraged.

## Carried forward

- Gate a verdict on per-span OCR confidence when the point depends on a single token (point 3).
- `partial` needs a worked convention: it was used once here and its meaning is currently only as
  clear as one example makes it. Second and third uses should be checked against this one.
- This example is a natural regression fixture — the same inputs should produce the same verdicts
  once the engine exists, and any drift is a signal.

---

## Reproduced by the engine (same day)

`domain/rubric/` was built and this run repeated through it, end to end, over the manual LLM queue
(`scripts/run_evaluation.py judge`) — no API key, the production code path. Output: **8 hit, 1
partial, 1 missed, 0 unsupported, 0 not judged**, group `treaty-features` reading *5 of 6 made, 3
expected — more than the question rewards*. Every quote was located in the transcript by string
search, so no verdict rested on the model's word alone. Frozen as
`benchmarks/fixtures/mains-eval/gs1-2024-q2.yaml` and replayed by
`apps/api/tests/test_rubric_engine.py`.

**Running it found a provenance bug that reading it would not have.** This rubric carried
`question_ref: {year: 2024, paper: mains-gs1, question_number: "2"}`. The engine resolves that
against the ingested corpus — and UPSC's actual 2024 GS1 Q2 is *"Estimate the contribution of
Pallavas of Kanchi for the development of art and literature of South India"*. The evaluator
cheerfully queued this answer for judging against the Pallavas question, with nothing on screen to
say so.

The rubric was wrong, not the lookup. This booklet is a **Vajiram & Ravi test-series paper** — the
probe above says so in its own first paragraph — so the question is not a UPSC question at all, and
the ref quietly claimed UPSC provenance for a coaching one. That is the same error the whole design
exists to avoid, arriving through a metadata field rather than through a score. Three changes
followed: the rubric schema now separates `question_ref` (a question the corpus holds, i.e. one UPSC
printed) from `question_text_en` + `question_source` (anything else, which must name where it came
from); `validate_rubrics.py` rejects a rubric that carries neither, both, or text without a source;
and the CLI prints the question and its provenance before every run, because the substitution was
invisible in the report and visible only in the queued prompt.
