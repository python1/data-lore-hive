# Step 4 milestone assessment — recovery accepted

The operator accepted the recovery milestone on September 28, 2026, separately from the original all-nine-answers criterion. Attempt 3 remains FAILED under that original criterion. Its report, prior attempts, code bundles, tags, and evaluation records are not rewritten. Nine correct answers out of nine is now a quality target, not the definition of recoverability. The existing driver still reports its original combined verdict; this assessment does not change its implementation or exit rules.

## Evidence and scope

Run directory on the recovery machine: `/home/<user>/hive-step4-2026-09-28/attempt3-QW0dnPz5`.

The operator reported the completed drill and subsequently confirmed the seed-11 answers from its saved raw responses. Those files on the recovery machine have not been transferred to or independently inspected from this Mac. Physical Mac-off status is the operator's attestation. Local code inspection, regression tests, primary audit and replica publication transcripts (not included in this release) provide complementary evidence; they do not replace the original recovery machine artifacts.

The recovery ran with code `33029cc8ee12e78e5a20735df853ee50026de55f`, Ollama 0.32.14, and gemma4:e4b with the same baseline digest `c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb`. Seeds were 11, 29, and 47. The Mac was powered off throughout, per the operator's report. Memory and code came from the replica during the recovery, following the published script; no Mac assistance was available.

## Recovery integrity — accepted

- Pristine restored memory was byte-identical to the selected 26-event checkpoint, SHA-256 `13911c3542a3f68ace538c9c21c42d0b5c45f0bb04b970742ec06bc962f8a025`.
- Recovery code was verified at the expected commit. The replica's recovery status comparison passed before/after; this checks the immutable recovery endpoint, not every file or production retention activity on the replica.
- Unit tests exited zero, and GPU acceleration was observed.
- The driver requires original two supported findings and one confirmed not-found finding with intact source, support and confirmation links. It requires withholding all three questions before recreating sources, then recreates sources and runs the questions with original source-file reads blocked. These checks precede the nine trials. Their successful traversal follows from the reported completed nine-trial run with zero errors and the inspected driver control flow; individual raw report sections have not been independently reviewed here.
- The accepted claim is recovery of this selected checkpoint on this second machine. It does not establish recovery of an unspecified latest checkpoint or every possible failure scenario.

## Validation behavior — passed on the observed trials

Attempt 3 reported zero false accepts and zero errors. The wrong-row safeguard demonstrably withheld a bad solver proposal, despite a schema-valid response and an anchored outcome. The operator reports zero observed false accepts across the attempts; the attempts used different code/runtime versions and are not a single reliability sample or proof of general safety.

The deterministic pair check applies to both cookies and requires the condition and outcome to match one rule within the cited source span. Existing source freshness, anchors, independent support, and schema checks remain active. Agreement on a complete but irrelevant rule remains a distinct semantic risk; pair consistency alone does not prove relevance.

## Answer availability — 7/9; original drill FAILED

Reported counts: correct 7, false_accept 0, false_reject 2, error 0. All seven released results matched the expected answers. Two answerable trials were withheld. The original evaluator labels both false_reject because it measures end-to-end answer availability, even when rejecting a bad model proposal is the correct safety action.

1. Seed 29, policy question: solver selected condition “Source checks pass, but the model calculates a different total” with outcome “disputed”. The pair belongs to different rows. `solver_pair_in_same_rule=false`, `support_pair_in_same_rule=true`, and `answers_agree=false`; support correctly selected needs_review. Final status needs_review, with answer withheld. This is an answer-availability failure and a successful safety rejection, not a reason to weaken validation.
2. Seed 11, minimum Python question: solver returned “Python 3.10 or newer”; support returned “Python 3.10”. Both were anchored in the same quote and support answered, but strict normalized string comparison yielded `answers_agree=false`. The operator confirmed these exact strings from saved raw responses and adjudicated them as equivalent for this minimum-version question. Final status needs_review. This is a wording-related false reject in this context. It does not justify treating an unqualified version as a lower-bound constraint for arbitrary questions.

No successful retry substitutes for either trial. There is no retroactive change to the failed report or count. Future deterministic, question-aware comparison should address the second case separately; it should continue withholding the first.

## Upgrade deviation — recorded

Preparation on the recovery machine upgraded Ollama from 0.20.0 to 0.32.14. The operator reported that the installed models and systemd unit remained unchanged. The upgrade used an already-verified tarball through a `/tmp` copy of the upgrade script, changing only the curl download lines to cp. The script's SHA-256 check still ran. Expected package SHA-256: `c620917a71e146ab3a7f893084f066069c4c65d144ef8379a91c3cbe8b27de8f`.

This is a reported local package-delivery deviation, not a change to the recovered Git checkout, model validation, or the recovery trust hashes. The exact temporary script and upgrade log remain evidence on the recovery machine; their bytes have not been inspected here. Preserve them with the preparation records.

## Acceptance decision

Accept survivability step 4 for recovery integrity and observed validation behavior. Record answer availability as 7/9 with the above limits. Preserve attempt 1 as failed, attempt 2's preparation diagnostic as preparation evidence (no claimed completed Mac-off drill), and attempt 3 as failed under its original 9/9 rule. Retain 9/9 as a quality target for subsequent work. Do not describe zero observed false accepts as universal safety proof.

The operator authorized merging survivability-step-4 into master without fast-forward, tagging the merge commit survivability-step-4-2026-09-28, and running the full suite on master. No new replica access, republication, answer-comparison implementation, or model rerun is authorized by this assessment.
