# Next milestone plan — structured deterministic answer comparison

Status: PLAN ONLY. No implementation, new model runs, replica changes, or publication. Begin future implementation on a new branch from the accepted step-4 master checkpoint. Keep historical attempts, tags, findings and raw responses unchanged.

## Objective and initial scope

Resolve the observed minimum-version wording false reject without accepting wrong constraints or weakening source validation. Start narrowly with unambiguous software minimum-version questions and a small documented grammar. Do not add fuzzy text similarity, embeddings, a model-based equivalence judge, broad negation rewriting, or an automatic retry-until-pass policy.

The motivating evidence is the operator's report of the same source quote supporting solver “Python 3.10 or newer” and support “Python 3.10” for “What is the minimum Python version required?”. Both original strings were anchored. Preserve the distinction between a version value answering a minimum-version question and an exact-version constraint answering a compatibility question.

## Deterministic representation

1. Recognize an explicit minimum-version question through a narrow deterministic question classifier. Establish the named product from that question or an unambiguous cited statement; do not infer an unspecified product from unrelated text.
2. Parse the verified cited span into a product and version constraint, for example product=Python, lower_bound=(3,10), inclusive=true. Record the exact source spans supporting the product, version and operator. Parse version components as integer tuples, never floating-point numbers.
3. Parse each cookie's original answer independently. A bare “Python 3.10” can denote the minimum value ONLY when the question explicitly asks for the minimum and the quoted source independently establishes that same inclusive lower bound. It must not be globally rewritten to “>=3.10”. Explicit “exactly”, “only”, “above”, “before”, upper bounds and negation retain their meaning; conflicts are refused.
4. Compare the typed answers with each other AND with the source-derived constraint. Both must be supported by that source and satisfy the requested slot. Comparison returns equivalent, different, or unclassified, with a deterministic reason. Different or unclassified version answers require review. An identical string must not bypass an unresolved constraint on this path.
5. Leave unrelated question types on their existing comparison path. Plan other types (numbers with units, dates, explicit Boolean propositions) separately after this grammar is validated.

Initially treat missing/extra version components, ranges, pre-release suffixes, multiple products, contradictory source statements, ambiguous dates and complex negations as unsupported unless explicitly covered by the grammar and tests. Do not assume 3.10 equals 3.10.0. Document exact supported and unsupported forms.

## Safety and audit integration

Apply structured comparison after existing schema and source checks, retaining independent support context, raw-response audit, source freshness, anchor checks, and policy pair-in-one-rule checks. Semantic equivalence never waives an anchor failure: if a paraphrase such as “>=3.10” is absent from a quote, the current anchor rule can still withhold it even when the comparator recognizes its meaning. The motivating real pair already passes anchoring.

Record original strings, source/citation IDs, requested answer type, parsed values, parser/rule version, exact supporting spans, comparison result, and why a bare version was interpreted as a minimum value. Keep raw strings and evidence intact; do not rewrite stored findings. The support cookie still receives only the question and cited evidence, never the solver's answer.

Expose solver/support originals and event IDs directly in new per-trial reports. Report recovery integrity, validation behavior and answer availability separately. Distinguish correct rejection of a bad proposal from a wording-related false reject. Preserve the legacy original reports and their 9/9 verdicts; identify any new evaluation policy by version.

## Regression matrix

Test the comparator in isolation AND the end-to-end acceptance gate. “Equivalent” below assumes all independent gates pass.

| Question/source context | Solver versus support | Required result |
|---|---|---|
| Minimum Python; source explicitly says 3.10 or newer | Python 3.10 or newer / Python 3.10 | Equivalent; recorded minimum-value interpretation |
| Same context with documented whitespace/case variation | Python 3.10 / python 3.10 | Equivalent |
| Minimum Python, inclusive bound | Python >=3.10 / Python 3.10 or newer | Comparator equivalent; acceptance still requires both anchors |
| Source requires >=3.10 | Python >3.10 / Python >=3.10 | Different; strict/inclusive operators preserved |
| Source requires >=3.10 | Python 3.10 only / Python 3.10 or newer | Different; extra restriction not discarded |
| Source requires >=3.10 | Python 3.1 / Python 3.10 | Different; component tuples, not decimals |
| Source requires >=3.10 | Python 3.9 / Python 3.10 | Different |
| Source requires >=3.10 | Python 3.11 / Python 3.10 | Different; a compatible version is not the minimum |
| Source names Python | Node.js 3.10 / Python 3.10 | Different product |
| General exact-version question | Python 3.10 / Python 3.10 or newer | Do not borrow the minimum-question rule |
| Source requires >3.10 | Both say Python 3.10 or newer | Withheld despite agreement; contradicts source operator |
| Source requires >=3.10 | Both say Python 3.9 | Withheld despite agreement |
| Version precision or release suffix unsupported | 3.10 / 3.10.0, or 3.10rc1 / 3.10 | Unclassified; no automatic equality |
| Ambiguous/negated/conflicting requirement | Both agree on an unsupported interpretation | Unclassified or unsupported; withhold |
| Valid policy table, exact seed-29 cross-row pair | Both cookies repeat wrong pair | Still needs_review |
| Missing/stale source, invalid quote or failed anchor | Equivalent normalized versions | Still withheld |
| Answer absent from retrieved source | Both independently confirm not found | Existing not-found handling and evidence preserved |

Add a diagnostic for both cookies choosing the same complete but irrelevant policy rule. It tests a different limitation from row consistency; report it honestly, do not make version normalization silently responsible for solving arbitrary policy relevance. Any required remedy should receive its own explicitly scoped plan.

## Validation and acceptance

- First preserve the raw-response excerpt from the recovery machine and exact quote as a regression fixture when the operator provides the artifact; do not fabricate raw Ollama output. Synthetic fixtures must be labeled synthetic. The confirmed pair can already drive a labeled regression based on the reported strings.
- Run all existing unit tests plus the equivalence/near-miss cases and negative gate tests. Include a mutation check in which permissive changes (operator removal, decimal version parsing, dropping product or source checks) must cause regression failures.
- Replay recorded responses deterministically so comparisons can be evaluated independently of model variability. Use isolated copies and new result files, never the primary or old trial directories.
- Run the existing table, prose and not-found evaluation suites under seeds 11/29/47 on the new code when implementation is authorized. Keep runtime/model digest and hardware recorded. Recovery host execution remains its agent's responsibility; deployment to the replica needs separate authorization.
- Success: the known minimum-version wording case is accepted for a documented source-supported reason; every specified near miss and existing unsafe case remains withheld; no observed false accepts; full suite passes. Publish answer availability separately. Nine out of nine remains a quality target, not permission to loosen checks or erase failures.

Only after review should implementation be considered for merging. No comparison implementation is included in the step-4 checkpoint.
