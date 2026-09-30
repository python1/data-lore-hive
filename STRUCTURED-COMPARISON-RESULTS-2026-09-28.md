# Structured minimum-version comparison — results

Implemented on `structured-minimum-version-comparison`, based on master
`4ccf0290f3eaaae5f2f6377065a0adc34dc7b12d`. No merge, tag changes, replica
access, or changes to the recovery machine. Historical records remain unchanged.
The preserved `STRUCTURED-COMPARISON-PLAN.md` is the original plan, not a status report.

## Measurement completion and results

The usage-limit interruption did not stop the measurement process. Both saved
reports have `finished: true`, contain all 30 trials, and are retained verbatim
in `structured-comparison-records-2026-09-28/{before,after}.json`. No rerun was
necessary. The after-report implementation hashes match the measured Python
files. All before/after model request payloads are identical, including seeds,
prompts and schemas. Frozen source IDs and source/database fixtures were shared
between phases; each phase queried its own database copies.

Mac, Ollama 0.32.14, gemma4:e4b digest
`c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb`,
seeds **11, 29, 47**, temperature **0.2**. Hardware/platform and raw responses
are in each report. This is a Mac workload measurement, not a new Mac-off drill.

| Suite | Trials per phase | False accepts before → after | Correct answer availability before → after | Confirmed not-found before → after | Other withheld before → after |
|---|---:|---:|---:|---:|---:|
| Table | 18 | 0 → 0 | 6/6 → 6/6 | 9 → 9 | 3 → 3 |
| Prose holdout | 3 | 0 → 0 | 3/3 → 3/3 | 0 → 0 | 0 → 0 |
| Three drill questions | 9 | 0 → 0 | 6/6 → 6/6 | 3 → 3 | 0 → 0 |

Availability here counts delivered correct answers among answerable trials.
Including correct confirmed absence, determinate outcomes are 15/18, 3/3,
and 9/9 respectively, unchanged. The three table abstentions have no retrieval
candidates; they are not answerable false rejects. Both phases have zero
answerable false rejects and zero errors. This sampled live result is separate
from the synthetic policy diagnostic below.

The Mac did not reproduce the wording mismatch seen on the recovery machine during these runs;
there is no measured live availability improvement to claim. A deterministic
fixture using the operator's confirmed seed-11 strings demonstrates the intended change:
`Python 3.10 or newer` versus `Python 3.10` was withheld on master and is now
accepted for the explicit minimum question and inclusive source constraint.
The quote fixture is synthetic; no raw-response artifact from the recovery machine was invented.

## Implementation and evidence

`version_comparison.py` uses rule `minimum-version-v1`. It parses product,
integer version components, and operator separately. A bare value becomes an
inclusive minimum only when both the question and cited source establish that
meaning. Both cookies must agree with each other AND the source constraint.
Unknown grammar or a mismatch is withheld. Identical answer text cannot bypass
an unresolved minimum constraint.

All existing source freshness, citation, anchor, schema, policy same-row,
independent support and raw-response audit checks remain. An equivalent symbolic
paraphrase still fails acceptance if it is not anchored. General question
comparison is unchanged. Minimum-version absence cannot be established by this
narrow grammar and remains needs_review, with independent absence evidence
preserved; other confirmed not-found handling is unchanged.

An `answer_comparison` event records original strings, parsed values, exact
source spans, rule version, interpretation and reason, source/chunk/hash, and
both model-call event links. Regular withheld results do not expose an answer.
The saved-results audit confirms raw response links for all calls, all existing
acceptance checks passing for delivered answers, and all three new comparison
events linked correctly. Primary database SHA-256 remains
`13911c3542a3f68ace538c9c21c42d0b5c45f0bb04b970742ec06bc962f8a025`.

## Regressions and supported grammar

**142 unit tests pass**, including 14 new regression tests with parameterized
cases. The initial missing-module failure and the baseline reported-pair failure
are preserved. Near misses withheld include strict `>` versus inclusive `>=`,
3.1 versus 3.10, exactly/only versus or-newer, higher/lower minima, another
product, extra version components, prerelease suffixes, contradictory or negated
sources, unknown question grammar, missing citation, stale source and bad anchor.
All existing policy row-consistency tests still pass.

Four deliberately permissive mutations are caught: operator removal (6 failing
assertions), product removal (2), source-check removal (4), decimal version
comparison (2). The original decimal mutation harness produced an error on a
three-component version; the corrected harness restricts decimal conversion to
two components and is caught by assertions with zero errors. Both mutation
records are preserved. The test log includes four nonfatal SQLite connection
ResourceWarnings; test exit status was zero.

Recognized question forms (case/spacing insensitive):
- What is the minimum PRODUCT version [required]?
- What is the minimum version of PRODUCT [required]?

Recognized complete quoted requirement forms:
- Requires PRODUCT VERSION or newer / or later.
- PRODUCT >=VERSION is required.
- PRODUCT VERSION or newer / or later is required.
- Minimum PRODUCT version [required] is VERSION.

Products are single identifiers, optionally dotted (such as Node.js). Versions
have two or three numeric components, without leading zeroes; different
component counts are not equated. Answers must name the product. One optional
trailing sentence is recognized: `The scripted mode needs no ...`, with a
bounded list drawn from services, packages, weights and network connections.
Arbitrary trailing text is not ignored. Conditional requirements, ranges,
multiple products, contradictory statements, prereleases, unsupported question
phrasing and unsupported source clauses stay unclassified on this path.
Non-minimum question types retain their existing path.

## Separate policy diagnostic and remaining work

The planned synthetic control has **one false accept before and one after**:
both mocked cookies choose the same coherent but irrelevant policy row.
For a calibration question, they choose the seal-open row and return `locked`
instead of `inspection_required`. Same-row consistency, anchors and agreement
all pass. This is an existing question-to-rule relevance gap, not a version
comparison regression. Its full results and reproducer are preserved separately;
it is not included in the zero-false-accept live-batch totals.

A follow-up should bind the question's condition to the selected policy rule
with a documented deterministic grammar and withhold ambiguous matches. That
policy change is outside this minimum-version-only implementation. The zero
observed false accepts in the live samples do not establish universal safety.

No requested Mac measurement or implementation work remains incomplete.
Recovery host validation of this new comparator has not run and was not part of
this Mac milestone. The exact raw quote artifact from the recovery machine remains unavailable;
the regression provenance above is explicit. Neither deployment nor merge is
performed.

## Reboot auto-sync check

Both user LaunchAgents, `local.hive.sync` and `local.hive.sync-watchdog`, were
loaded (scheduled idle, last exit 0). Local status showed last success
2026-09-28 20:10:01 CDT, pending_changes=false, consecutive failures=0,
last_error=null, and 2 cached retained generations. This was a local cached
status inspection, not a connection to the replica. Complete outputs are preserved
in `AUTO-SYNC-REBOOT-2026-09-28.json` and
`AUTO-SYNC-REBOOT-LAUNCHAGENTS-2026-09-28.json` (neither is included in this public release).

## Reproduction and records

From the repository, run `python3 -m unittest discover` for the full suite and
`PYTHONPATH=. python3 structured-comparison-records-2026-09-28/mutations.py`
for mutation checks. The preserved measurement harness takes code directory,
new output root, phase name and primary database path as four arguments. It
requires a running local Ollama and refuses an existing phase directory.
The original isolated databases and fixtures remain under the workspace's
`work/structured-comparison`; committed JSON reports preserve all trial events,
raw responses, original cookie answers and gold labels independently of those
scratch databases. New measurements must use new directories.
