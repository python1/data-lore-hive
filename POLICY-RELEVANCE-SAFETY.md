# Production policy relevance safety split

This branch takes the deterministic binding, decision-first independent relevance
contract, raw evidence, full condition qualification, provisional provenance, and
list/inspect/revoke/affected interfaces from `policy-relevance-lore` at c93a174.
Qwen diagnostics and live promotion work remain on that experimental branch.
Existing tags, records, and primary memory are preserved. No replica access.

## Production authority

`lore.EXPERIMENTAL_PROMOTION` is False, with no CLI or environment opt-in.
Promotion, renewal, and active promoted reuse are disabled. Imported promoted
records remain inspectable but do not authorize answers. Fresh fallback still
runs on an unclassified question; prior revocation/quarantine/audit blocks are
not erased. Successful fallback records provisional evidence for audit and
revocation, never a production shortcut. Automatic trap/promotion workflows are
not invoked after production answers. Manual qualify still performs a fresh
answer check; it cannot enable promotion.

The lifecycle implementation remains dormant for history compatibility and
explicit synthetic tests; those tests patch the switch only inside their test
process. Experimental promotion is not a supported production configuration.
Every deterministic mismatch/conflict fails closed, before model fallback.
All anchors, same-row checks, independent support agreement, source freshness,
and raw-response evidence remain. Policy absence proposals still withhold:
failure to bind is not proof that an answer is absent.

## Audit commands (Mac, repository directory)

```
python3 lore.py --db knowledge.sqlite3 list
python3 lore.py --db knowledge.sqlite3 inspect MAPPING_ID
python3 lore.py --db knowledge.sqlite3 affected MAPPING_ID
python3 lore.py --db knowledge.sqlite3 revoke MAPPING_ID --reason 'Audit explanation'
python3 knowledge.py --db knowledge.sqlite3 findings
```

Revocation flags prior dependent deliveries and excludes them from the trusted
answer view. It cannot undo actions taken on past answers. Historical findings
without mappings are not retroactively revalidated by this change.

## Scope of safety claims

The known literal calibration/seal wrong-row answer is deterministically blocked.
Independent calls to the same model do not provide statistical independence.
A correlated wrong fallback judgment can still accept an irrelevant row; the
preserved intentional injection demonstrates this. No claim of universal safety
is made. Production disables amplification through learned authority, not the
possibility of an initial model mistake. Conservative parsing can reduce
availability; fallback adds up to two relevance calls per request.

The legacy synthetic evaluator explicitly enables experimental lifecycle tests
in its synthetic sections only; promoted results there are not production-path
measurements. Production-specific tests separately verify enough votes/traps
cannot promote, imported promotion cannot bypass fresh validation, malformed
fallback withholds, the calibration/seal trap, and dependent revocation.

## Final validation — 2026-09-30

Gemma e4b, Ollama 0.32.14, seeds 11/29/47, temperature 0.2. New isolated
30-trial measurement, with raw response events in safety-records-2026-09-30/live-30.json.
Production implementation hashes match the code used at measurement start.

| Suite | Trials | Correct positive / answerable | Confirmed not-found | Withheld | False accepts | Errors |
|---|---:|---:|---:|---:|---:|---:|
| Table | 18 | 3/6 | 9 | 6 | 0 | 0 |
| Prose | 3 | 3/3 | 0 | 0 | 0 | 0 |
| Drill questions | 9 | 3/6 | 3 | 3 | 0 | 0 |

Compared with master before this split: table drops from 6/6 to 3/6, drill from
6/6 to 3/6, prose remains 3/3. Six answerable policy paraphrases cleanly abstain;
three other table cases withhold because retrieval has no candidates. This is
the explicitly accepted safety/availability tradeoff, not an accuracy pass.
Per workload path: general 0/21 false accepts (6 positive, 12 absence, 3 withheld),
deterministic 0/3 (3 positive), fallback 0/6 (all withheld); promoted has no trials.

Separate 18 live binding probes: deterministic 6/6 answerable bindings and
3 abstentions; fallback 3/6 answerable bindings and 6 abstentions. Zero false
accepts/errors on both paths. Calibration/seal literal cases are deterministic;
paraphrase succeeds, negated/unspecified selectors withhold, injected-source
probes withhold. All 14 scripted gate cases match their expected behavior,
including a deliberately malformed response being withheld. Intentional
correlated-error controls yield 1 fallback false accept and 1 experimental
promoted false accept; these are explicit residual-risk demonstrations, not
observed live rates. The promoted control enables experimental code only in
its isolated test process.

182 unit tests pass, including six production-default/safety tests. Existing
nonfatal SQLite ResourceWarnings remain. Primary knowledge.sqlite3 unchanged:
13911c3542a3f68ace538c9c21c42d0b5c45f0bb04b970742ec06bc962f8a025.
Qwen/promotion remains unmerged on policy-relevance-lore at c93a174.
