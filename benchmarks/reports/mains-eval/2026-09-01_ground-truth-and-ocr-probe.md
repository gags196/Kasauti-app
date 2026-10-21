# Mains evaluation: ground-truth availability and a first OCR probe

*2026-09-01. Two gating checks run before any evaluator code was written. The first returned a
negative result that changed the product design; the second was encouraging but is incomplete.*

## Check A — is there any UPSC-marked ground truth? **No.**

The plan had assumed publicly-distributed "topper answer copies" could be joined to UPSC's published
paper-wise marksheets to produce a labeled corpus, replacing a blocker that had stood for months.
They cannot.

**UPSC has never released an evaluated answer booklet**, with one court-ordered exception (Gaurav
Gupta, 2012). The Supreme Court upheld non-disclosure — examiner anonymity is the stated reason —
and the Delhi High Court later rejected a plea seeking answer sheets plus model answers under RTI.

What actually circulates under the name "topper answer copy" is one of two things, and neither is
the marked exam script:

| Artifact | What it is | Marks on it |
|---|---|---|
| Test-series copy | Written for a coaching mock. InsightsIAS describes its library as "authentic answer copies written by toppers **during our UPSC Mains Test Series**" | A *coaching* evaluator's, when present |
| Fair copy | Rewritten neatly after the fact for distribution. UnlockIAS: "most copies are **unmarked fair copies**" | None |

Of 640+ PDFs in the largest public library, roughly **5 carry any evaluator verdict at all**, and
those verdicts are coaching evaluators' — a population documented as inconsistent enough that
aspirants report "wildly different scores and comments" for the same answer from different markers.

Confirmed first-hand below: the booklet inspected is a Vajiram & Ravi test-series booklet whose
printed evaluation grid (Introduction / Body / Conclusion / Presentation / **Marks**) is **entirely
blank**, as is its "Suggestions" box.

**Consequence.** A topper's real GS4 mark was earned by a sealed script nobody has seen; the
circulating document is a different artifact. Joining the two would attribute a UPSC mark to
something UPSC never marked.

**This is the finding, not a setback.** UPSC-grounded accuracy is unobtainable *for anyone*, which
is precisely why every "98% accuracy" / "99% closest to human checking" claim in this market is
unverifiable — and why the CCPA has already fined coaching institutes ₹11L and ₹5L for that class of
claim.

**Design consequence, adopted:** the evaluator does not predict marks. It reports which rubric points
an answer hit and missed, quoting the evidence from the learner's own text. Score prediction has no
observable truth; rubric-point detection does, and turns validation into precision/recall on a
labelling task that one competent reader can adjudicate.

## Check B — can a vision model read a real handwritten answer? **Yes, on this sample.**

**Sample:** Shakti Dubey (AIR 1, CSE 2024), GS Paper 1, Vajiram & Ravi test-series booklet.
53 pages, 13.7 MB, no text layer (`is_scanned: true`, 22 text-layer characters total).
Rendered at scale 2 (1191×1682 px) via `scripts/pdf_pages.py`.

**Printed question, read without difficulty:**

> 2. Evaluate the role of subsidiary alliance policy in turning 'the British Empire in India' into
> 'the British Empire of India'. (10 marks, 150 words)

**Handwritten answer (pages 3–4 of the booklet), transcribed at high confidence:**

> Advent of British in India as a trading company & their withdrawal as a colonial power was
> possible because of their imperialist policies, one of the most important being — Subsidiary
> Alliance.
>
> Subsidiary Alliance:
> (1) This policy was put forward by Richard Wellesley
> (2) The states which signed Subsidiary Alliance Treaty could not have an army of their own
> (3) They had to station British army in their territory, which were to be maintained by the states
>     themselves
> (4) The state could not have any independent foreign policy
> (5) They could not engage with Portuguese or French without permission of British
> (6) One British official was to be stationed in their court.
>
> Hyderabad, Bha[ra]tpur, Satara, Jaunpur and more states fell prey to this British policy of
> paramountcy.
>
> This was further extended by "Doctrine of Lapse" under Dalhousie, under which states that had
> signed Subsidiary Alliance were annexed on grounds of no biological heir / maladministration.
>
> Thus Subsidiary Alliance led to annexation of various territories & further led to expansion of
> British control & helped in establishing the British Empire.

### What this tells us

**Encouraging.** The script is legible cursive and transcribed cleanly. More importantly the answer
is **structurally rubric-shaped** — intro, a definition, six enumerated treaty features, named
annexed states, an extension mechanism, a conclusion tying back to the question's wording. Those are
exactly the discrete, checkable content points the reframed product needs to detect. A rubric for
this question writes itself from the answer's own shape.

**The documented failure mode reproduced immediately, on the transcriber.** One state name is
written ambiguously. The historically correct princely state is **Bharatpur**; the pen-strokes read
closer to "Bhagatpur". The transcriber's instinct was to silently normalise it to the name that
*ought* to be there. That is precisely the hallucination skew the literature reports — on handwritten
mathematics, **87% of grading errors traced to transcription failure rather than rubric
misapplication, skewed 2.5:1 toward inventing a correct answer out of unclear handwriting**. A model
that knows the history will smooth the handwriting toward what it expects, and will then award the
rubric point either way. Any transcript this system produces must be surfaced for learner
confirmation before evaluation, and uncertain spans must be marked rather than silently resolved.

**Three reasons this number is optimistic and must not be generalised:**

1. It is a **fair copy** — rewritten unhurried for publication — not script produced under a
   three-hour exam clock.
2. It is a **topper's** handwriting, self-selected for legibility by the institute that published it.
3. It is **English**. Devanagari is untested here and is the harder case; the "96% Devanagari
   accuracy" figures in circulation are *isolated character classification*, not running page-level
   handwriting, and do not transfer.

A further practical note: the publisher's watermark overlays the text and degrades legibility. Real
learner submissions will not carry watermarks but will carry worse problems — phone-camera skew,
shadow, and creased paper.

## Still outstanding

- **Hindi / Devanagari OCR is unmeasured.** This is the fairness-critical case: Hindi is
  low-resource for this task, and the default hypothesis must be that the system finds fewer rubric
  points in Hindi answers of equal quality — harming the cohort with the least access to good human
  evaluation, and violating the repo's bilingual-parity invariant. Needs its own sample.
- **Exam-condition script is unmeasured.** Hurried, dense, corrected-in-place writing under time
  pressure is a different regime from anything published.
- **CER/WER are not yet quantified.** This probe establishes feasibility, not a number. Producing a
  real figure needs ~50 hand-transcribed pages spanning both languages and both legibility regimes.

## Method note

Sources for Check A: UPSC's non-disclosure position and the *Gaurav Gupta* exception; Delhi HC
rejection of the RTI plea; InsightsIAS' and UnlockIAS' own descriptions of their libraries. Check B
used `scripts/pdf_pages.py info` / `render` — the same tooling the ingestion pipeline uses — and the
booklet was read directly rather than through any OCR service, so the result describes a frontier
vision model's ceiling, not a commodity OCR baseline.
