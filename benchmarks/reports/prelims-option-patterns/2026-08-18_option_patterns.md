# Prelims MCQ Option-Pattern Analysis

Does the *construction* of the options leak the answer? Pure statistics over
questions with an official answer key loaded — no model involved.

Three things to read before the numbers:

- **The baseline is not 25%.** In roughly half these questions the options are
  "1 only / 2 only / Both 1 and 2 / Neither 1 nor 2", where "Both 1 and 2" is
  mechanically the longest string. Length-based rates are therefore compared
  against a null built by permuting which option is correct *within each option
  archetype*, not against a flat quarter.
- **Five hypotheses are tested**, so the threshold is Bonferroni-corrected to
  alpha = 0.010. At a nominal 0.05 one false positive per report
  is expected by construction.
- **A verdict of 'not a usable signal' is the useful answer**, not a failure. A
  pattern that fires at chance is worth knowing does not work.

## 2022 onwards — the current pattern

*494 keyed questions · 2022–2026 · scope: 2022–latest*

Answer-letter distribution: A 119 · B 134 · C 128 · D 113
(chi-square 2.11, df 3, p 0.549)

| Hypothesis | n | rate | baseline | basis | p | verdict |
|---|---:|---:|---:|---|---:|---|
| Correct option echoes a sibling option | 494 | 24.5% | 23.6% | archetype-permutation | 0.6338 | not a usable signal |
| Escape-hatch option ('none of the above' / 'Neither 1 nor 2') is the answer | 119 | 19.3% | 25.0% | share-of-options | 0.1530 | not a usable signal |
| Longest option is the answer | 353 | 19.3% | 23.4% | archetype-permutation | 0.0683 | not a usable signal |
| A dated option (containing a specific year) is the answer | 2 | 50.0% | 25.0% | share-of-options | 0.4142 | too few questions to conclude anything |
| One answer letter is over-represented | 494 | 27.1% | 25.0% | uniform-over-labels | 0.5492 | not a usable signal |

- *Correct option echoes a sibling option*: mean sibling overlap: correct 0.392 vs any-option 0.385
- *Longest option is the answer*: ties excluded — a tie is the absence of a signal, not a weak one
- *One answer letter is over-represented*: chi-square 2.11, most frequent letter B

Option-set construction in this era:

- subset_of_numbered: 225 (45%)
- entity_choice: 185 (37%)
- count_of_correct: 90 (18%)

## Before 2022 — context only

*897 keyed questions · 2013–2021 · scope: earliest–2021*

Answer-letter distribution: A 205 · B 252 · C 232 · D 208
(chi-square 6.53, df 3, p 0.088)

| Hypothesis | n | rate | baseline | basis | p | verdict |
|---|---:|---:|---:|---|---:|---|
| Correct option echoes a sibling option | 897 | 22.7% | 24.3% | archetype-permutation | 0.2932 | not a usable signal |
| Escape-hatch option ('none of the above' / 'Neither 1 nor 2') is the answer | 156 | 26.3% | 25.0% | share-of-options | 0.7115 | not a usable signal |
| Longest option is the answer | 586 | 24.4% | 24.5% | archetype-permutation | 1.0000 | not a usable signal |
| A dated option (containing a specific year) is the answer | 13 | 53.8% | 59.6% | share-of-options | 0.5485 | too few questions to conclude anything |
| One answer letter is over-represented | 897 | 28.1% | 25.0% | uniform-over-labels | 0.0884 | not a usable signal |

- *Correct option echoes a sibling option*: mean sibling overlap: correct 0.388 vs any-option 0.384
- *Longest option is the answer*: ties excluded — a tie is the absence of a signal, not a weak one
- *One answer letter is over-represented*: chi-square 6.53, most frequent letter B

Option-set construction in this era:

- subset_of_numbered: 508 (56%)
- entity_choice: 386 (43%)
- ordering: 6 (1%)

## All years pooled

*1391 keyed questions · 2013–2026 · scope: all published questions*

Answer-letter distribution: A 324 · B 386 · C 360 · D 321
(chi-square 8.32, df 3, p 0.040)

| Hypothesis | n | rate | baseline | basis | p | verdict |
|---|---:|---:|---:|---|---:|---|
| Correct option echoes a sibling option | 1391 | 23.4% | 24.0% | archetype-permutation | 0.6154 | not a usable signal |
| Escape-hatch option ('none of the above' / 'Neither 1 nor 2') is the answer | 275 | 23.3% | 25.0% | share-of-options | 0.5083 | not a usable signal |
| Longest option is the answer | 939 | 22.5% | 24.2% | archetype-permutation | 0.2091 | not a usable signal |
| A dated option (containing a specific year) is the answer | 15 | 53.3% | 55.0% | share-of-options | 0.8575 | too few questions to conclude anything |
| One answer letter is over-represented | 1391 | 27.7% | 25.0% | uniform-over-labels | 0.0399 | not a usable signal |

- *Correct option echoes a sibling option*: mean sibling overlap: correct 0.390 vs any-option 0.385
- *Longest option is the answer*: ties excluded — a tie is the absence of a signal, not a weak one
- *One answer letter is over-represented*: chi-square 8.32, most frequent letter B

Option-set construction in this era:

- subset_of_numbered: 733 (52%)
- entity_choice: 571 (41%)
- count_of_correct: 90 (6%)
- ordering: 6 (0%)
