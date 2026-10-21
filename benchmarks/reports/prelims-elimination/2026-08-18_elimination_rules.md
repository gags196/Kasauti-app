# Prelims Elimination-Technique Verification

Fifteen elimination rules, taken from the coaching-circuit elimination-rule list, tested
against every Prelims Paper 1 question with an official answer key. No model is
involved: in the 'Consider the following statements' family the correct option
*enumerates which statements are true*, so the key is a per-statement truth label.

Read these before the table:

- **The baseline is not 50%.** UPSC writes more true statements than false ones,
  and each question's true-count is fixed by its key. Every statement rule is
  scored against a hypergeometric null built per question, so a marker that fires
  on nothing in particular lands on the baseline instead of looking like a find.
- **15 rules means a Bonferroni threshold of alpha = 0.0033.** At a nominal 0.05, testing 15 rules
  produces a 'pattern' every run by construction.
- **The rate reported is the rate at which the marked statement is TRUE.** A rule
  that works for elimination shows a rate *below* its baseline — that is the
  'usable inverse signal' verdict, and it is the good one.
- **'Not a usable signal' is a finding.** The document's own confidence figures
  are quoted in the table so the gap is visible rather than argued about.

Not tested, because nothing in the corpus can decide them: the examiner-psychology
claims ('fear of the unknown'), the cognitive-overload claims, and the bilingual
etymology decoding. They are opinions about intent, not measurable properties of a
printed paper. The 'Chinese Checkers' keyword-mirroring rule is measured in the
option-pattern report instead, where it came back at p = 0.79.

## All years — the full evidence

*692 questions decoded · 2095 statements (1630 of them claims) · 2013–2026 · scope: all published questions*

Base rate: **59.8%** of decoded claim statements are true.

**Usable rules in this era: 1 of 15.**

| Rule | family | n | true rate | baseline | p | verdict | the document claims |
|---|---|---:|---:|---:|---:|---|---|
| Statement contains an extreme modifier (only, all, never, any, no, must) | statement | 213 | 41.8% | 49.2% | 0.0018 | USABLE INVERSE SIGNAL | ~1% to 5% correct — 'heavily incorrect' |
| Statement contains a moderate modifier (some, may, generally, one of the) | statement | 147 | 75.5% | 68.2% | 0.0075 | not a usable signal | ~95% to 99% correct |
| Statement asserts an absolute absence ('there is no …') | statement | 19 | 47.4% | 55.3% | 0.5831 | too few to conclude anything | 'almost universally incorrect' |
| Statement claims a first ('world's first', 'first time') | statement | 27 | 55.6% | 54.7% | 1.0000 | too few to conclude anything | ~90% to 95% correct — the counter-intuitive exception |
| Statement joins two clauses with but / yet / whereas | statement | 43 | 46.5% | 53.9% | 0.2488 | not a usable signal | 'overwhelmingly incorrect' — the error hides in the second clause |
| Statement attributes something in the passive ('developed by …') | statement | 13 | 15.4% | 57.7% | 0.0026 | too few to conclude anything | ~90%+ incorrect — names and ministries are swapped |
| Statement carries a rigid number (a percentage or a statutory count) | statement | 26 | 53.8% | 57.7% | 0.7664 | too few to conclude anything | 'usually altered and incorrect' |
| Statement carries a rounded or tapered target ('nearly', 'net zero by 2070') | statement | 53 | 50.9% | 54.7% | 0.6077 | not a usable signal | 'generally correct' — flexible targets are not tampered with |
| Statement names a specific year | statement | 65 | 53.8% | 52.5% | 0.8959 | not a usable signal | milestone years are 'intentionally tampered with' |
| Statement is framed as recent ('recently', 'in the news') | statement | 8 | 25.0% | 31.2% | 1.0000 | too few to conclude anything | 'almost always correct' — verified current affairs |
| Statement uses an imposing tone (must adopt, shall replace, mandate) | statement | 60 | 61.7% | 53.5% | 0.0821 | not a usable signal | 'almost always incorrect'; enabling language is correct |
| The longest statement in the question | statement | 560 | 58.4% | 59.2% | 0.6508 | not a usable signal | verbosity is a time-drain device, not a truth signal |
| Two statements on the same theme are never both true | question | 44 | 43.2% | 46.8% | 0.6535 | not a usable signal | 'they are never both true' — a 1-correct, 1-incorrect pair by construction |
| Option joins two entities with a hyphen ('Jaipur-Atroli Gharana') | option | 19 | 31.6% | 25.4% | 0.5980 | too few to conclude anything | 'usually the correct answer' |
| The option least like its siblings is the answer | option | 340 | 25.0% | 24.9% | 1.0000 | not a usable signal | the thematic outlier 'is determinative' |

- *Statement contains an extreme modifier (only, all, never, any, no, must)*: in 158 questions
- *Statement contains a moderate modifier (some, may, generally, one of the)*: in 100 questions
- *Statement asserts an absolute absence ('there is no …')*: in 18 questions
- *Statement claims a first ('world's first', 'first time')*: in 25 questions
- *Statement joins two clauses with but / yet / whereas*: in 35 questions
- *Statement attributes something in the passive ('developed by …')*: in 13 questions
- *Statement carries a rigid number (a percentage or a statutory count)*: in 18 questions
- *Statement carries a rounded or tapered target ('nearly', 'net zero by 2070')*: in 45 questions
- *Statement names a specific year*: in 52 questions
- *Statement is framed as recent ('recently', 'in the news')*: in 8 questions
- *Statement uses an imposing tone (must adopt, shall replace, mandate)*: in 42 questions
- *The longest statement in the question*: ties excluded
- *Two statements on the same theme are never both true*: 190 two-statement questions, 44 of them sharing wording at Jaccard >= 0.25
- *Option joins two entities with a hyphen ('Jaipur-Atroli Gharana')*: questions printing exactly one hyphenated-name option
- *The option least like its siblings is the answer*: ties excluded

What decoded, and what did not:

- decoded (subset): 668
- no numbered statements: 632
- count question, partial information: 42
- decoded (count_extreme): 24
- options are not statement references: 14
- negative polarity: 13
- unkeyed or dropped: 6
- options reference a statement that is not printed: 1

## 2022 onwards — does the rule survive the pattern change?

*234 questions decoded · 710 statements (586 of them claims) · 2022–2026 · scope: 2022–latest*

Base rate: **63.7%** of decoded claim statements are true.

**Usable rules in this era: 0 of 15.**

| Rule | family | n | true rate | baseline | p | verdict | the document claims |
|---|---|---:|---:|---:|---:|---|---|
| Statement contains an extreme modifier (only, all, never, any, no, must) | statement | 75 | 52.0% | 52.3% | 1.0000 | not a usable signal | ~1% to 5% correct — 'heavily incorrect' |
| Statement contains a moderate modifier (some, may, generally, one of the) | statement | 59 | 79.7% | 72.1% | 0.0800 | not a usable signal | ~95% to 99% correct |
| Statement asserts an absolute absence ('there is no …') | statement | 6 | 33.3% | 41.7% | 1.0000 | too few to conclude anything | 'almost universally incorrect' |
| Statement claims a first ('world's first', 'first time') | statement | 8 | 62.5% | 62.5% | 1.0000 | too few to conclude anything | ~90% to 95% correct — the counter-intuitive exception |
| Statement joins two clauses with but / yet / whereas | statement | 14 | 42.9% | 59.5% | 0.2396 | too few to conclude anything | 'overwhelmingly incorrect' — the error hides in the second clause |
| Statement attributes something in the passive ('developed by …') | statement | 7 | 14.3% | 59.5% | 0.0223 | too few to conclude anything | ~90%+ incorrect — names and ministries are swapped |
| Statement carries a rigid number (a percentage or a statutory count) | statement | 15 | 60.0% | 64.4% | 0.9087 | too few to conclude anything | 'usually altered and incorrect' |
| Statement carries a rounded or tapered target ('nearly', 'net zero by 2070') | statement | 19 | 68.4% | 65.7% | 0.9884 | too few to conclude anything | 'generally correct' — flexible targets are not tampered with |
| Statement names a specific year | statement | 20 | 70.0% | 60.0% | 0.4308 | too few to conclude anything | milestone years are 'intentionally tampered with' |
| Statement is framed as recent ('recently', 'in the news') | statement | 3 | 66.7% | 50.0% | 1.0000 | too few to conclude anything | 'almost always correct' — verified current affairs |
| Statement uses an imposing tone (must adopt, shall replace, mandate) | statement | 22 | 59.1% | 51.5% | 0.4568 | too few to conclude anything | 'almost always incorrect'; enabling language is correct |
| The longest statement in the question | statement | 195 | 66.2% | 63.8% | 0.4485 | not a usable signal | verbosity is a time-drain device, not a truth signal |
| Two statements on the same theme are never both true | question | 10 | 50.0% | 44.2% | 0.7582 | too few to conclude anything | 'they are never both true' — a 1-correct, 1-incorrect pair by construction |
| Option joins two entities with a hyphen ('Jaipur-Atroli Gharana') | option | 6 | 33.3% | 21.9% | 0.6185 | too few to conclude anything | 'usually the correct answer' |
| The option least like its siblings is the answer | option | 108 | 27.8% | 24.9% | 0.5042 | not a usable signal | the thematic outlier 'is determinative' |

- *Statement contains an extreme modifier (only, all, never, any, no, must)*: in 56 questions
- *Statement contains a moderate modifier (some, may, generally, one of the)*: in 36 questions
- *Statement asserts an absolute absence ('there is no …')*: in 6 questions
- *Statement claims a first ('world's first', 'first time')*: in 8 questions
- *Statement joins two clauses with but / yet / whereas*: in 14 questions
- *Statement attributes something in the passive ('developed by …')*: in 7 questions
- *Statement carries a rigid number (a percentage or a statutory count)*: in 11 questions
- *Statement carries a rounded or tapered target ('nearly', 'net zero by 2070')*: in 17 questions
- *Statement names a specific year*: in 18 questions
- *Statement is framed as recent ('recently', 'in the news')*: in 3 questions
- *Statement uses an imposing tone (must adopt, shall replace, mandate)*: in 15 questions
- *The longest statement in the question*: ties excluded
- *Two statements on the same theme are never both true*: 52 two-statement questions, 10 of them sharing wording at Jaccard >= 0.25
- *Option joins two entities with a hyphen ('Jaipur-Atroli Gharana')*: questions printing exactly one hyphenated-name option
- *The option least like its siblings is the answer*: ties excluded

What decoded, and what did not:

- decoded (subset): 210
- no numbered statements: 207
- count question, partial information: 42
- decoded (count_extreme): 24
- options are not statement references: 7
- negative polarity: 6
- unkeyed or dropped: 3
- options reference a statement that is not printed: 1

## Before 2022 — context

*458 questions decoded · 1385 statements (1044 of them claims) · 2013–2021 · scope: earliest–2021*

Base rate: **57.6%** of decoded claim statements are true.

**Usable rules in this era: 1 of 15.**

| Rule | family | n | true rate | baseline | p | verdict | the document claims |
|---|---|---:|---:|---:|---:|---|---|
| Statement contains an extreme modifier (only, all, never, any, no, must) | statement | 138 | 36.2% | 47.5% | 0.0002 | USABLE INVERSE SIGNAL | ~1% to 5% correct — 'heavily incorrect' |
| Statement contains a moderate modifier (some, may, generally, one of the) | statement | 88 | 72.7% | 65.7% | 0.0621 | not a usable signal | ~95% to 99% correct |
| Statement asserts an absolute absence ('there is no …') | statement | 13 | 53.8% | 61.5% | 0.7470 | too few to conclude anything | 'almost universally incorrect' |
| Statement claims a first ('world's first', 'first time') | statement | 19 | 52.6% | 51.4% | 1.0000 | too few to conclude anything | ~90% to 95% correct — the counter-intuitive exception |
| Statement joins two clauses with but / yet / whereas | statement | 29 | 48.3% | 51.1% | 0.8453 | too few to conclude anything | 'overwhelmingly incorrect' — the error hides in the second clause |
| Statement attributes something in the passive ('developed by …') | statement | 6 | 16.7% | 55.6% | 0.1198 | too few to conclude anything | ~90%+ incorrect — names and ministries are swapped |
| Statement carries a rigid number (a percentage or a statutory count) | statement | 11 | 45.5% | 48.5% | 1.0000 | too few to conclude anything | 'usually altered and incorrect' |
| Statement carries a rounded or tapered target ('nearly', 'net zero by 2070') | statement | 34 | 41.2% | 48.5% | 0.3973 | not a usable signal | 'generally correct' — flexible targets are not tampered with |
| Statement names a specific year | statement | 45 | 46.7% | 49.1% | 0.8018 | not a usable signal | milestone years are 'intentionally tampered with' |
| Statement is framed as recent ('recently', 'in the news') | statement | 5 | 0.0% | 20.0% | 0.4533 | too few to conclude anything | 'almost always correct' — verified current affairs |
| Statement uses an imposing tone (must adopt, shall replace, mandate) | statement | 38 | 63.2% | 54.6% | 0.1688 | not a usable signal | 'almost always incorrect'; enabling language is correct |
| The longest statement in the question | statement | 365 | 54.2% | 56.8% | 0.2538 | not a usable signal | verbosity is a time-drain device, not a truth signal |
| Two statements on the same theme are never both true | question | 34 | 41.2% | 47.8% | 0.4946 | not a usable signal | 'they are never both true' — a 1-correct, 1-incorrect pair by construction |
| Option joins two entities with a hyphen ('Jaipur-Atroli Gharana') | option | 13 | 30.8% | 27.7% | 0.7630 | too few to conclude anything | 'usually the correct answer' |
| The option least like its siblings is the answer | option | 232 | 23.7% | 24.7% | 0.7612 | not a usable signal | the thematic outlier 'is determinative' |

- *Statement contains an extreme modifier (only, all, never, any, no, must)*: in 102 questions
- *Statement contains a moderate modifier (some, may, generally, one of the)*: in 64 questions
- *Statement asserts an absolute absence ('there is no …')*: in 12 questions
- *Statement claims a first ('world's first', 'first time')*: in 17 questions
- *Statement joins two clauses with but / yet / whereas*: in 21 questions
- *Statement attributes something in the passive ('developed by …')*: in 6 questions
- *Statement carries a rigid number (a percentage or a statutory count)*: in 7 questions
- *Statement carries a rounded or tapered target ('nearly', 'net zero by 2070')*: in 28 questions
- *Statement names a specific year*: in 34 questions
- *Statement is framed as recent ('recently', 'in the news')*: in 5 questions
- *Statement uses an imposing tone (must adopt, shall replace, mandate)*: in 27 questions
- *The longest statement in the question*: ties excluded
- *Two statements on the same theme are never both true*: 138 two-statement questions, 34 of them sharing wording at Jaccard >= 0.25
- *Option joins two entities with a hyphen ('Jaipur-Atroli Gharana')*: questions printing exactly one hyphenated-name option
- *The option least like its siblings is the answer*: ties excluded

What decoded, and what did not:

- decoded (subset): 458
- no numbered statements: 425
- negative polarity: 7
- options are not statement references: 7
- unkeyed or dropped: 3
