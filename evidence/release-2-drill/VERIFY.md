# Verifying the release-2 recovery drill

This folder lets anyone check the signatures and hash chain behind the release-2 recovery-tested pin described in the [README](../../README.md). The signed files are published exactly as they were produced. Nothing that is signed or hashed has been edited.

## What is here

| Path | What it is |
|---|---|
| `allowed_signers` | The release-signing **public** key, in `ssh-keygen -Y` format, under identity `aster-hive` and namespace `hive-release` |
| `release-2/manifest.json`, `release-2/manifest.sig` | Signed release 2 manifest and its signature |
| `pin-manifest.json`, `pin-manifest.json.sig` | Signed recovery-tested pin and its signature, taken byte-for-byte from the pin upload envelope |
| `run/evidence-index.json` | Sealed inventory of the drill run: 317 relative paths with SHA-256 values. The pin signs its hash |
| `run/…` | The 28 indexed evidence files that passed the leak scan, unchanged, at their indexed paths |
| `withheld.json` | The 289 indexed files that are not published, each with its index hash and a reason |
| `verify_evidence.py` | Runs every check below (Python 3 standard library plus `ssh-keygen`) |

Expected signing key fingerprint: `SHA256:ZozTASM/tPWZPMpUaYnP5tYJsVWNbANnRnjjYkx5j4A`. Compare it with a copy you got another way if you have one. A key published next to the signatures it verifies only proves those signatures came from that key.

## Quick check

```bash
git clone https://github.com/python1/data-lore-hive.git
cd data-lore-hive/evidence/release-2-drill
python3 verify_evidence.py
```

It should end with `ALL CHECKS PASSED` and exit 0. It needs OpenSSH 8.2 or newer for `ssh-keygen -Y verify`.

## The same checks by hand

Run these from `evidence/release-2-drill/`.

**1. Signing key fingerprint**

```bash
cut -d' ' -f3- allowed_signers > /tmp/hive-release-signing.pub && ssh-keygen -lf /tmp/hive-release-signing.pub
```

Expected: `256 SHA256:ZozTASM/tPWZPMpUaYnP5tYJsVWNbANnRnjjYkx5j4A no comment (ED25519)`

**2. Release 2 manifest signature**

```bash
ssh-keygen -Y verify -f allowed_signers -I aster-hive -n hive-release \
  -s release-2/manifest.sig < release-2/manifest.json
```

Expected: `Good "hive-release" signature for aster-hive with ED25519 key SHA256:ZozTASM/…`

**3. Pin signature**

```bash
ssh-keygen -Y verify -f allowed_signers -I aster-hive -n hive-release \
  -s pin-manifest.json.sig < pin-manifest.json
```

**4. The pin names this exact release manifest**

```bash
python3 -c "import hashlib,json; p=json.load(open('pin-manifest.json')); h=hashlib.sha256(open('release-2/manifest.json','rb').read()).hexdigest(); print(p['release']); print(h); print('MATCH' if p['release']==h else 'MISMATCH')"
```

Both lines should read `1b8a64fccf29289967d532ae323f52922d81dce0b94c4a9569050dc842f5e13b`.

**5. The pin names this exact evidence index**

```bash
python3 -c "import hashlib,json; p=json.load(open('pin-manifest.json')); h=hashlib.sha256(open('run/evidence-index.json','rb').read()).hexdigest(); print(p['drill_sha256']); print(h); print('MATCH' if p['drill_sha256']==h else 'MISMATCH')"
```

Both lines should read `e6a5e703674275708c3596b8d235004b7752c5981a13d1c91fe1c0a4ac7a3ef6`.

**6. Every published evidence file matches its index hash**

```bash
python3 -c "
import hashlib,json,os
idx=json.load(open('run/evidence-index.json'))['files']; w=json.load(open('withheld.json'))['files']; bad=0
for k,h in sorted(idx.items()):
    p=os.path.join('run',k)
    if os.path.isfile(p): ok=hashlib.sha256(open(p,'rb').read()).hexdigest()==h
    else: ok=w.get(k,{}).get('sha256')==h
    bad+=not ok; print('OK  ' if ok else 'BAD ', 'published' if os.path.isfile(p) else 'withheld ', k)
print('mismatches:',bad)"
```

Expected: `mismatches: 0`, with 28 files `published` and 289 `withheld`.

**7. Read the results**

```bash
python3 -m json.tool run/report.json
cat run/unit-tests.stderr
```

`report.json` records `integrity: passed`, `pristine_final: passed`, `unit_tests: passed`, `pin_eligible: true`, and quality counts of 6 correct (3 correct answers plus 3 confirmed absences), 3 abstentions, 0 false accepts and 0 errors, with `target_pass: false`. `unit-tests.stderr` ends with `Ran 212 tests in 16.735s` and `OK`.

## What this proves

- The release-2 manifest and the pin were both signed by the holder of the published key, under the `hive-release` namespace.
- The pin refers to exactly this release manifest (commit `c8a784e9a0084559bd71524f07b9ab8478141fba`, bundle SHA-256 `b832cb5b…`) and to exactly this evidence index.
- Each published evidence file is byte-for-byte the file that was in the sealed run when the index was hashed, and therefore when the pin was signed.

## What this does not prove

- **The code is not here.** The Git bundle (`hive.bundle`) and the recovered checkout belong to the private repository. You can check that the manifest names commit `c8a784e…` and a bundle hash, but you cannot rebuild or run that code, or confirm that the 212 tests are the tests you would expect. The public tree on `master` is a separate redacted export.
- **289 indexed files are withheld** (listed below), including the memory database, the drill baseline, the model trial records (`trials.jsonl`, `quality.json`), the integrity report (`integrity.json`), and every SSH command record. Their hashes are in the signed index, so they cannot be swapped without detection, but you cannot read them. The trial counts above therefore come from `report.json`, a summary written by the drill runner, not from the raw trials.
- **`evidence.json` is withheld.** The release manifest signs its hash (`evidence_sha256` = `77a2bd85…`), but it contains a private local path, so you cannot check that link.
- **The main machine being off is the operator's statement**, recorded as `"mac_off": "operator-confirmed; not remotely measured"`. Nothing here measures it.
- **A signature means approval, not truth.** The key holder signed after reviewing the evidence. The signature does not show that the runner, its tests or the model behaved correctly beyond what the files themselves record. The runner's own review and hashes are in the withheld baseline.
- **Key custody and pin upload are not shown.** Nothing here shows where the private key is kept, or that the replica accepted the pin. Acceptance and read-back of pin sequence 1 are reported by the operator.

## Withheld files

Each hash below is copied from `run/evidence-index.json`. `verify_evidence.py` confirms that every withheld file is in the index with that hash and is not present here.

| Indexed path | SHA-256 (from index) | Reason |
|---|---|---|
| `baseline.json` | `8a1ef72c18c39f723dedf54029871d13033a6b450258c1b2f892cdd449efa179` | drill baseline (private paths and host key) |
| `checkpoint-wire.command.json` | `4e082c7c9e0f578abd5abede75d8c54ea6d4a9243a6640d88282f84fa507053a` | contains private host details (LAN address, account name or home path) |
| `checkpoint-wire.stdout` | `71edb7ff5ff6d2cf49bca4f282b8c8cd7a534b6006d01b7ad5e4adcfa2278285` | memory database checkpoint stream |
| `clone.command.json` | `ce764f95c5faf214822360a238509155271d53a3202f6603520eabe53c1b5e5d` | contains private host details (LAN address, account name or home path) |
| `clone.stderr` | `119fe78b2cbdfe1b81ab3d26e0b22639633a5264fbaa2372158c9c39066bd33a` | contains private host details (LAN address, account name or home path) |
| `ct-code-status.command.json` | `8837e907ee815fdca6c440c01f2d05504272ebd3fe236f17b4f414ac83ceeae2` | contains private host details (LAN address, account name or home path) |
| `ct-memory-status.command.json` | `84b60e6ff0def517fb47dc7f1593931ece7f732db4135c9cf8c5549e648db23c` | contains private host details (LAN address, account name or home path) |
| `download-evidence.json.command.json` | `aa3bc814cb6cedf1bbdf177fa2b603bb67ca4917957d209f8af7e2f8d0b01090` | contains private host details (LAN address, account name or home path) |
| `download-evidence.json.stdout` | `77a2bd85451108f67eac25cc4a5cee65a4e7ad72e5736e184dd36f4a3d7792f0` | contains a private local filesystem path |
| `download-hive.bundle.command.json` | `67adfb9af998849482cec459fd601dee1bce91a3cca09f7e3c27325fd6fe136a` | contains private host details (LAN address, account name or home path) |
| `download-hive.bundle.stdout` | `b832cb5bc3bf0fdf1c46630a9b9312ba6ce38d1a1cf65be01fcaed1bf7f7cbb8` | Git bundle of private release code |
| `download-manifest.json.command.json` | `a0fd35c4ae100f115b03520baf44d7ea9f36f4f68e8867d6836c5298328947a0` | contains private host details (LAN address, account name or home path) |
| `download-manifest.sig.command.json` | `41846b904dd329aa1fba16ce71bf080b0948609236438007a2638f29509c9c54` | contains private host details (LAN address, account name or home path) |
| `integrity-worker.command.json` | `7fe8785dcedb69922d9c9317fc798de0904b8f969a75f3bf0f9b8682bc375c22` | contains private host details (LAN address, account name or home path) |
| `integrity.json` | `2b52b2a728bd053ee10d1256f86c924e41be61ecf79432852e945eba292bd1be` | contains private host details (LAN address, account name or home path) |
| `known_hosts` | `f230729954ab7cb7944b4ebf93706143f9ddcecc78db6a30602a076085d4c704` | SSH known_hosts |
| `memory/knowledge.sqlite3` | `13911c3542a3f68ace538c9c21c42d0b5c45f0bb04b970742ec06bc962f8a025` | SQLite memory database |
| `quality-worker.command.json` | `b0fb755b76752ee2468f4fe3ef2703bf914911ad8ce3b4907493a4cbe4246053` | contains private host details (LAN address, account name or home path) |
| `quality.json` | `87819711d2e2579194b823219886bcb95b759de47113927156bced505bdcf7fb` | contains private host details (LAN address, account name or home path) |
| `recreated-sources/source-recovery.json` | `0a64e4e0f068ded08b41fd9416a83ee136a043b4de0e01618d8cfc9eb8544efd` | contains private host details (LAN address, account name or home path) |
| `release-phone-receipt.json` | `34ce292b8c812068ea76cc7af9ac91ca25e681d8cdc8aa64f697dbadf4fb9e04` | operator receipt |
| `release/evidence.json` | `77a2bd85451108f67eac25cc4a5cee65a4e7ad72e5736e184dd36f4a3d7792f0` | contains a private local filesystem path |
| `release/hive.bundle` | `b832cb5bc3bf0fdf1c46630a9b9312ba6ce38d1a1cf65be01fcaed1bf7f7cbb8` | Git bundle of private release code |
| `trials.jsonl` | `f26570a2443096d958860e082adc6b59bcf9c97b69339ec46cfc9acadfa92027` | contains private host details (LAN address, account name or home path) |
| `working-events.json` | `ed403be68811a23a8f124f3839135f99d53cdfd4e7906fb3abed8c5140d76d44` | contains private host details (LAN address, account name or home path) |
| `working.sqlite3` | `f68d7aea339b813e16c7c3cf690be3ff3cc3b7295b3d5a8d90ef8ba29dff21c5` | SQLite memory database |
| `working.sqlite3-shm` | `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb` | SQLite memory database |
| `working.sqlite3-wal` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | SQLite memory database |

<details>
<summary>recovered-code/ — 261 files of the private release-2 checkout</summary>

| Indexed path | SHA-256 (from index) |
|---|---|
| `recovered-code/.git/HEAD` | `659200d9d675927fe36d4d0f35522df73ce00ef85eaf1bb1c247ebbf3d24e130` |
| `recovered-code/.git/config` | `b44a65cb2146b7ca57ab6e92f0d0989ddc885bb11c993b25775781c55e6fa58b` |
| `recovered-code/.git/index` | `df2ae0c943c4974afde151580acbf056f94b848a976c668b582a93384615e512` |
| `recovered-code/.git/logs/HEAD` | `fa2d6cdb07e55dcd80d85187ddad9beec93916ac2d786e00e2903fb86edd7310` |
| `recovered-code/.git/logs/refs/heads/master` | `b5456e79b18c1cff9ca28d20e00698309af6853ec39b53430fb91dfc3672e3cf` |
| `recovered-code/.git/objects/pack/pack-64555a109c6eff17d2b2b475208817bb02000477.idx` | `9e60473f59085c007e8bf49dcff6624613001e05bf44fcb8d7d93d86b9efc5f6` |
| `recovered-code/.git/objects/pack/pack-64555a109c6eff17d2b2b475208817bb02000477.pack` | `ded32605778ebb450d02bae1d6aa531aaa5c90d58ba311156ea7f18b26cf8404` |
| `recovered-code/.git/objects/pack/pack-64555a109c6eff17d2b2b475208817bb02000477.rev` | `246222ac3071dbea8de9d7716de94c2cb900a0ef2ceafca5fe348c8ee8493057` |
| `recovered-code/.git/packed-refs` | `1d33a967558d02f80519a2250319574838a1e1865c8b2abc11cbff0ab5339d3b` |
| `recovered-code/.git/refs/heads/master` | `659200d9d675927fe36d4d0f35522df73ce00ef85eaf1bb1c247ebbf3d24e130` |
| `recovered-code/.gitignore` | `aeed864602342947914fd6c2225f8249d3b73e43dd47000e9a00cb5c99ac39e2` |
| `recovered-code/ABSENCE-AND-PROSE.md` | `2852070fa249da05281baf3ee22e3e59b567bb74a52a2aca18414a8917143c00` |
| `recovered-code/ABSTENTION-FORMAT.md` | `6845d9eacf87042ccfd09686e00f7398211c6e1733d3bbba6cf8b1956ca5136c` |
| `recovered-code/ALIENWARE-ATTEMPT1-FAILED-2026-09-28.md` | `ce3011ff77fd20861ba7998feb6238d3ba5ac375f8824cbc1c739a44e0af5595` |
| `recovered-code/ALIENWARE-ATTEMPT2-RUNBOOK-2026-09-28.md` | `7503b39b354215b6c1ab26444467da0c7cb5dde23fb2d5a72fd3c3435339793e` |
| `recovered-code/ALIENWARE-RECOVERY-FINAL-2026-09-28.md` | `86a152858aebc5a70b7315a462ef67ee141f60072ea38ab6c3531e80dfa02523` |
| `recovered-code/ATTEMPT2-BUNDLE-TESTS-2026-09-28.txt` | `84b0facb02c45e337a78015d2c364fd5e1d57c5ed2a4cfaa063605641265f6b6` |
| `recovered-code/ATTEMPT2-MAC-AUDIT-2026-09-28.json` | `710a528498570491ac7f12160fc39440da5ce2ab5f44fc8e27429ab063bdb4cd` |
| `recovered-code/ATTEMPT2-MAC-SCHEMA-2026-09-28.jsonl` | `ab955cdcb17dc644a101534bcae61c90441e48a3756eee2ca17e4a76dc3cf758` |
| `recovered-code/ATTEMPT2-PREPARATION-2026-09-28.md` | `535fa1c8396a8c8112ecb5950fc443b55905308c212045baf4fbc6cbb9b61c69` |
| `recovered-code/ATTEMPT2-UPDATER-LOCAL-CHECK-2026-09-28.py` | `33ba913aec06ddeaa052a6ecf699a80f3fe15e50db87ad86789f21e48dc558b1` |
| `recovered-code/ATTEMPT2-UPDATER-LOCAL-CHECK-2026-09-28.txt` | `4fd38ecb587422483cdb72da8035a20d7226a4847eea29440f67647bd4dce1dd` |
| `recovered-code/ATTEMPT3-BUNDLE-TESTS-2026-09-28.txt` | `83c2ec711f2cf7501e65f27ff1731533e511cd683b3e18f785498416cfc2b1de` |
| `recovered-code/ATTEMPT3-PUBLICATION-2026-09-28.md` | `e091dc2094feec0ceaf5126378ecc5cf073380fd22f7189bbd14e07eefe4c4c3` |
| `recovered-code/ATTEMPT3-UPDATER-LOCAL-CHECK-2026-09-28.py` | `43769a5c6364432c1281947d061d3a050d4143b5c24f7bb36ac37a256dc1f8d9` |
| `recovered-code/ATTEMPT3-UPDATER-LOCAL-CHECK-2026-09-28.txt` | `6b8b322b89a38f2fec90b623a7602ca23af78bc4f5dc41c6a5fc462d0108e486` |
| `recovered-code/AUTO-SYNC-ENABLED-2026-09-27.json` | `5bbebdb286861226146a6303ba9ff0b4efe9a82dc7f47aec4b8d7006feb82d7f` |
| `recovered-code/AUTO-SYNC-ENABLED-2026-09-27.md` | `41e8a8aadb3528f35d13c37b83fb4c760cf530a9c25a8019b808fdae56550942` |
| `recovered-code/AUTO-SYNC-INSTALL-2026-09-27.md` | `5af4465080aea9323ce2143bd5f389bd9b1072a10e68961fc312187018a090cf` |
| `recovered-code/AUTO-SYNC-LIVE-2026-09-27.json` | `e5db71e1cc0ed69a56656a8bb92e1effa8dcb018611ab8a4e3d5c6199c3191ff` |
| `recovered-code/AUTO-SYNC-LIVE-2026-09-27.md` | `1cb704d65e16c089c3a4940db38be18dc3a09c384d7b08929532237048f5f712` |
| `recovered-code/AUTO-SYNC-REBOOT-2026-09-28.json` | `c60f9ec4b3e4d8860d567f12703c2bf6e9c2002ba8d055176cf6115c115e27c1` |
| `recovered-code/AUTO-SYNC-REBOOT-LAUNCHAGENTS-2026-09-28.json` | `8459c3d21a7ef9891794e6e8c0cd325b3dc50ceb00da0b816bd585ed09e1f9c1` |
| `recovered-code/BATCH-EVALUATION.md` | `1c363e893826e76fe56d889918cda897aa9648b85b4d51c901e675ad7f393710` |
| `recovered-code/CHECKPOINT.md` | `dcc5dedfac69f975f6cb6dbf60d8c803cffeac7bcdaaf9fbe9e8b70259333cc8` |
| `recovered-code/CROSS-MACHINE-RECOVERY.md` | `0a63b4f0cf15030557eedf5565a1dbb7cfa80098c9039f3e4c6f782b9e05226a` |
| `recovered-code/CT104-ATTEMPT2-PUBLICATION-2026-09-28.txt` | `bbba6d21e9a2d479cb0fc49f215a22a66add68dd2fe6ba2393cd3b245cbc44bd` |
| `recovered-code/CT104-ATTEMPT3-PUBLICATION-2026-09-28.txt` | `9042014206cc67c4762acbfa20407864c376e14fdc2afad08495941d69af0760` |
| `recovered-code/CT104-POST-INSTALL-2026-09-28.json` | `68233de52a10d074cac811f0c963a386c5c5bb7c8d7feaf484b87af5fc8cb24a` |
| `recovered-code/CT104-ROOT-INSTALL-2026-09-28.json` | `b4d6b3fd3ff2d70cfeea32f7100ef646fe5754550c56a1396dda50628d70a336` |
| `recovered-code/CT104-ROOT-INSTALL-2026-09-28.txt` | `d600801c3ee5044efa39cb462fed5edc05af90a0d39afd4e42cc9d5f73e0b3d7` |
| `recovered-code/POLICY-RELEVANCE-SAFETY.md` | `2cf90bbbb41677f5c4a67610969d53dc568c16967c44ec8d1aafd585ec21a0da` |
| `recovered-code/POLICY-ROW-CONSISTENCY-2026-09-28.md` | `b3cc57d2ffc562aab7959c0c00a579e16ae100bb7c7ce1b90232d1485cfa90c1` |
| `recovered-code/PRIMARY-POLICY-PAIR-AUDIT-2026-09-28.json` | `19fe4ff90188a4e7f039a9b9a099ce77da3d8dfa0787b9fadf5464d70f4229db` |
| `recovered-code/PROJECT-STATE.md` | `aeab88df19d1f2c5cdc0c99d4a337b827e006eb31532d1449020a4bbac763a41` |
| `recovered-code/README.md` | `9aeb5f6b2a22ac956025509b24a2836a72c22a87c0c120cbf5accadef345e564` |
| `recovered-code/RECOVERY-CONSOLE-TRANSFER-2026-09-27.md` | `111ba8bb0f9bb00dd5ac982cf65087098fd4b6807d8507d4f2e1d43cb7497285` |
| `recovered-code/RECOVERY-KIT-READY-2026-09-27.md` | `205b28013032c186a9a9a1fe6f7c1461cc012aa0132ce34d036a489b97a1e408` |
| `recovered-code/RECOVERY-KIT-VALIDATION-2026-09-27.json` | `1b2dcf15467e30fd2d611d9962b9608cb14aedeea4b2c3f518b72ff5cef0bffb` |
| `recovered-code/RECOVERY-KIT-VALIDATION-2026-09-28.json` | `a882b540cba7de3fb771880307e4d837a881a175136ef3eaa22f0d765e11e17e` |
| `recovered-code/RECOVERY-PHONE-2026-09-27.txt` | `2457bd2cdf0b8768f36a55fa720edae3e2db524dbcfb0aaae2648a6adac0b277` |
| `recovered-code/RECOVERY-PHONE-2026-09-28.txt` | `8645bbd57e668f3b6ac48f65f75fc67bd6676d910f23ec5def7b636ce5bd744e` |
| `recovered-code/RECOVERY-PHONE-ATTEMPT2-2026-09-28.txt` | `f25b68cf89ec58a851c0ca42911a0e61845056e7ae3366abb041cc6060230926` |
| `recovered-code/RECOVERY-PHONE-ATTEMPT3-2026-09-28.txt` | `9d2610a95e6bd1a1b96599df73272f417f62f1931c1fe55b38f167be6208fc69` |
| `recovered-code/RERUN-2026-09-26.md` | `54a073b385b736ea609d92de1ab93754958ad8dd24e6d867fb5f363ab0f44b41` |
| `recovered-code/REVIEW-POLICY-ANALYSIS.md` | `c8bed50b355a873f72b9a729d8720beb069dde7d5c412920cb4ccddf52928606` |
| `recovered-code/SIGNED-CODE-RECOVERY-HANDOFF.md` | `e1182ac13147b4338c21cee07194cf5146e698d6ae1daa71c9655b9329c90e8b` |
| `recovered-code/SOURCE-RECOVERY-SEEDS-2026-09-27.md` | `c9f2bb1b85f4cf956d8a51554c3be92a705e0a5b7b8f50fda3e69af9257f8242` |
| `recovered-code/SOURCE-RECOVERY.md` | `f941de5c592f793d1564bfb6d151d6e50922919331db7d36df1ed15926f5307c` |
| `recovered-code/STEP4-INSTALL-RESULTS-2026-09-28.md` | `486458e8be9557284d22963fbf7d02d7c36d7e7ff9be5c33b18868f1fb90069d` |
| `recovered-code/STRUCTURED-COMPARISON-PLAN.md` | `68c8b52ea3cff6a4aedf02c1a008c4b337cad2cbd51f49264081c1c3e6d80bc1` |
| `recovered-code/STRUCTURED-COMPARISON-RESULTS-2026-09-28.md` | `1ee86c7fc9f6015a1d66aab103bae1f15fda9515f0175a19988b922e98e32f99` |
| `recovered-code/STRUCTURED-POLICY-before-question-routing.md` | `04c8ba5fdc9a117105175fd92dcaf7a23b1526ed1bc2a46c71ed16830c8bf9c1` |
| `recovered-code/STRUCTURED-POLICY.md` | `539f032f019822c93d20c171fb0aeceaffe12b1b9117d179846fecce3c4122b7` |
| `recovered-code/SUPPORT-CHECK.md` | `52a2e763c767bef2365c5d0ffbcc95a8985ae3d2664a9d66c449efed027c816d` |
| `recovered-code/SURVIVABILITY-COVERAGE-2026-09-27.md` | `a413a5f210368fa6ab4de2dac1b7784b108b13477a32a3b6289ab19dfec9c021` |
| `recovered-code/SURVIVABILITY-RESULTS-2026-09-27.md` | `bc70223e640a6285537b93d1c3dfcbf412213ed783b16df288129fd2567f7480` |
| `recovered-code/SURVIVABILITY-STEP4-ASSESSMENT-2026-09-28.md` | `0800ef5d0ffdc91e75fa9ab5e3c3db2413439a8e7b768a33879e2ac7ee3c2849` |
| `recovered-code/SURVIVABILITY.md` | `bc116c4b0eb5d5573a952952bdd6aeb379af9c6ab121cb520fa8ef2aca5f0e0a` |
| `recovered-code/TABLE-CONTEXT.md` | `6da31d93a44e46c108425a80f187eb01b54a4b4a8ef4a3197abaeeece3a3960b` |
| `recovered-code/__pycache__/hive.cpython-312.pyc` | `e966def51acbd6180a75c267bff2ba4a53c209cfcc4a784ea8f1b574372fc497` |
| `recovered-code/__pycache__/lore.cpython-312.pyc` | `06e997214ace28c1c2b7453529b99df18f29de0545da8f3e9e54e71528408431` |
| `recovered-code/__pycache__/ollama_local.cpython-312.pyc` | `19541ed5ea9a834bb2c8f59ee3def02858e5e3ec9273c3da80a5606544b8ab33` |
| `recovered-code/__pycache__/policy_binding.cpython-312.pyc` | `ef8062ef5e8632be1e5deb518026ff1ebef8970f4c3cf9655dec248d2424ac5b` |
| `recovered-code/__pycache__/policy_relevance.cpython-312.pyc` | `6cd01e1b350a993129d5476fbd6ac73ed1d09de9076b310502a91c8ea3036e12` |
| `recovered-code/__pycache__/policy_slots.cpython-312.pyc` | `33ba24a722e200a16162451ddc113946fcc0b9b8f28a61255a195c5f79613b03` |
| `recovered-code/__pycache__/policy_tables.cpython-312.pyc` | `4df13b417db003663d1e9fae2b35d2edd5207268cac4d94bb949100c8d2a3e4b` |
| `recovered-code/__pycache__/relevance_cookie.cpython-312.pyc` | `57153086445866f76bd1625b1c3e1d547409f2a416c588e2bb23cf35d4f9df0b` |
| `recovered-code/__pycache__/source_recovery.cpython-312.pyc` | `bf0f05611e3985556cb404c0e19b982860cdeb9aad4fbe73658977174c41239f` |
| `recovered-code/__pycache__/support_cookie.cpython-312.pyc` | `a35c83495793b41ecaac54bbae5693955e82de2fc759f2a0ad686887657c6c61` |
| `recovered-code/__pycache__/version_comparison.cpython-312.pyc` | `3e4f68d4565b9367a4013fa576bf56489d8ac71fa1906fb386bc9c6067e1d85e` |
| `recovered-code/absence-confirmation-live-query.json` | `6d9c702df2cf0cc3317ad58e7aec4d88c7e0719db05aa000c94b389256ae9d8a` |
| `recovered-code/absence-confirmation-validation.json` | `42e301515bdc2f65d040cbc1fab023c35d69dc6d3c46cd74bd83de393a17aee5` |
| `recovered-code/abstention-format-validation-b3acd7b3.json` | `36378aaa8e7ef1cbc023ca38fd9314bacb90c349a56bba7143e7073cd4224c79` |
| `recovered-code/attempt3-mac-off.sh` | `36a277e855a80ecff68abc6fa80d29bf529676e1165408655b384cd2e28fe4dc` |
| `recovered-code/audit_policy_pairs.py` | `80f792959996f7b6ff1e9f6491572e25676f23a77830793250f0c8c069e2995b` |
| `recovered-code/batch-validation-1d3dc0b9.json` | `f092ab8414ce53594359d86b3f10f4a0f0d347c71714cf4879295d315c3a9efc` |
| `recovered-code/build_code_installer.py` | `72c60d0cce645da6036982e5274ac1a6d54f15af060c9d93fb9a2422d0b34dce` |
| `recovered-code/build_recovery_kit.py` | `0d0e4cbf2c3dd4e6dfab67d3ddf3b400a2c1a924232c21b416b2e3da66146ca6` |
| `recovered-code/code_builder.py` | `b6f27fa2cb031df7c28b58f8f06b4c5ef89f3a954cec71300515202fe55f777b` |
| `recovered-code/code_publisher.py` | `ba1ba5e88a87dcf72958b0a4f193a980cb3ab1eba0926526b99691d73579db1d` |
| `recovered-code/code_release.py` | `ed664236c17e5a2289beeac22c59361b6bc6404034a5b3b1adc798fccebc4d57` |
| `recovered-code/code_sync.py` | `4135fe2b1c30b0924ab88dcc222cb168f29f4bccd9fd0310d63e1d8354fed3f8` |
| `recovered-code/code_transport.py` | `459a141577d10ee602cd4d4d54dc13b46c89a8b63600308ee95247e35b6a19c8` |
| `recovered-code/condition-slot-validation.json` | `f4fc40f1d8850a558f6be8d65b7aeca14086dbde2163916f61f102e63a25ab7b` |
| `recovered-code/cross_machine_recovery.py` | `b6267d2a4f27a5b381c4b4829deadf69e453c6dc2cb60f7190ab5d63d7dd8734` |
| `recovered-code/diagnose_prose_nonanswer.py` | `132a5034b2fb63925c430e714db291c6d7ef9baea9bf9d8fdbb4044c984f2bb2` |
| `recovered-code/evaluate.py` | `9dfb7626e25763580d5b6a6019dfa7e75277e1743f21bfa26370527131134db4` |
| `recovered-code/evaluate_batch.py` | `54973b27cf76c94493900a2981d6434e2222d8988dcc62e59f7c0463e05958ab` |
| `recovered-code/evaluate_policy_holdout.py` | `4da25cb89a7b5f5b7487037e05cf96ac94f8e760a23eb395495d740a86a2bc31` |
| `recovered-code/evaluate_policy_relevance.py` | `47b1455d28b9c0b79a1ae66cfc0ae26cfc2a3571b7d77b628fa69dc5a61e9ca6` |
| `recovered-code/evaluate_prose_policy.py` | `f1b742d540aa8bad3ef99e6688b748356fad4843f84ae1e3cb699df9bce32795` |
| `recovered-code/evaluate_support.py` | `1eb63eb8eb45ba876763a78ba2b9a72b8d872238e95acf00b8112f64690f7897` |
| `recovered-code/gemma-validation.json` | `37aad764dbca42ff8db053f62cac96ea5a3d8d4a5b233cc46f53054fcefe8950` |
| `recovered-code/historical-quote-support-replay.json` | `e325fe7653c519d9fb692ec0a3f5e45373c97af52a57f4a911fcc09eca228c0c` |
| `recovered-code/hive.py` | `1aa6a46dfa7d2453f534cd84a655ce3cda38a45fa84745d73f7448f226ca11a6` |
| `recovered-code/install-ct104-retention.py` | `ba4ef5cb05c0d2ea3f39334085b9f73e5063d2cbfdd0d3a3ef54c539263bbf06` |
| `recovered-code/install_code_publisher.py` | `948a89be60bb3237f74275d6d37e7bc61d73feb88cc5caeed8210ba92849fff9` |
| `recovered-code/install_ct104_recovery.py` | `d355c882ef362f6ad831d1f731e74d37fd553ce5edf5f560388d3eaffa526f4b` |
| `recovered-code/install_mac_sync.py` | `6e4b82e3961c4bd5120034f9a0d290039bcf9dad8439f68a2c0ddf58ed948d9d` |
| `recovered-code/knowledge.py` | `256ec2746309bd396258513d860559fc87efbd7c9ad6c8baf8fd91b0ece6a699` |
| `recovered-code/local.hive.sync-watchdog.plist` | `49ceded9c26c2c2da9f8c7f8876198ee17ce4b4b0d1733299fbe44d5dfb5e167` |
| `recovered-code/local.hive.sync.plist` | `896eeef06aff755efaeccc63fbe41558418e593aed9857180a9f39cd56352ead` |
| `recovered-code/lore.py` | `2e30f82936a39dd5de2ca4f66c5d695644d135d2b097b44c9fc32fa0c18a652e` |
| `recovered-code/measure_rerun.py` | `f8a8fc1da6c09be78cd59dd78726e2562b23f253d4a4c7823dbc94d5e4c43e1f` |
| `recovered-code/ollama_local.py` | `8fd57bb798e3cb81931527c5530a87ccb10e45a1773d0cf3ce76618c5d4895c7` |
| `recovered-code/ollama_preflight.py` | `5e38e7a235629db312dd7871a747d90c23b1c82589482b046cad81e4d3b0b7b8` |
| `recovered-code/outcome-selection-attempt-1.json` | `de9e7910eaa45f9c02d60dc8382ba5ecb4d320cbaef469f897cd0df60a039311` |
| `recovered-code/policy-holdout-validation-7e145b8d.json` | `61ffc80509e28ee8f86d3a240e28d020e914d49331df58a766e66f4508a350bc` |
| `recovered-code/policy-parser-limitations-observed.json` | `f56e5c4a107d3b4aa7af07ff965c0a88c2e27db0d1e8b92d80e0cbe17f322154` |
| `recovered-code/policy_binding.py` | `37ecef8dedef144372ed201fda868469d5ae9cb9329d24c48ea423f5cbc90e98` |
| `recovered-code/policy_relevance.py` | `f1ae905c5012337317a673b3ab3f85e118314a4bbcf3647e37ea2c64bdbe4523` |
| `recovered-code/policy_slots.py` | `236b62be0c1a5f1c16c449f6cb1e1717c4a398a7f5d9e081ecff196b29b9a586` |
| `recovered-code/policy_tables.py` | `138323390f7427aa979b7f2bd3a045c27071639ca4a368c45bf37465592e3a45` |
| `recovered-code/prepare_mac_code_sync.py` | `631ab41c88aac42bd7f9b763a69c3597cafad4e88148b0c237aef1d618b92113` |
| `recovered-code/preserved-prose-replay-fa52a8fe.json` | `e9a84b924caf9ff8282dcc4fa4f12f22f674bdfce13f80cfd9077c6b9b1fe6f6` |
| `recovered-code/prose-current-validation-ab0af95d.json` | `d78c6236ab2d0aba6f9f52d2de5077bc446cacb84ca12d17b4325b816844ded5` |
| `recovered-code/prose-nonanswer-unfixed-e7a6c871.json` | `0f376aaf9ed4f01ff4d46a880829f3257351d5ca8dc015ca7067710502514dc5` |
| `recovered-code/prose-policy-validation-2147ce73.json` | `4aef6bf1537a9a3030d5ab8078ddde0c2b504b492eac3ee7ce9c50b805fc6124` |
| `recovered-code/question-routing-attempt-1.json` | `ddd0607da9e876abbf3eb68a6f3d0863a4ac9f28d6915480d539b54891f0725c` |
| `recovered-code/question-routing-attempt-2.json` | `7c2dceece9c2a29d614366b280f8f8e2b485e88176781fe2b8109371d7edf1b8` |
| `recovered-code/question-routing-attempt-3.json` | `3cecefb329b8a30e11af7ef07152f485a40e19d1a091e3411db8cf6317b024cc` |
| `recovered-code/question-routing-attempt-4.json` | `38ff46af6fd7d0d02468b8d5c5109ea8b863ca3e98090e2adfdeb0508191e234` |
| `recovered-code/question-routing-audit.json` | `632abd908d0c977d5847a0c7f1b9fa23b67aa4ec37352899f73425861ad642fd` |
| `recovered-code/question-routing-final.json` | `8b826dab508cd377b0af1565f8783c65632280fb2133961dab3364d0a1da4e25` |
| `recovered-code/recovery_server.py` | `8cef39b098dcf88fbc1961c18986504fd4553419abaf693db54dde5e4eb12a67` |
| `recovered-code/relevance_cookie.py` | `74dda520ea4b56510c22ed1d9fed8008281ad2460729415f269ef8dc4e6a1d64` |
| `recovered-code/replay_policy_measurement.py` | `bd535dfaf19242262154853b4091642f1c5be794185d7ce38c5060fa736de4c1` |
| `recovered-code/replication.py` | `902c4d633ea3db93cebe5448b626634a8ebf7d8c31e7a37d7a067cd1c61e10fa` |
| `recovered-code/rerun-2026-09-26-measurements.json` | `5c31be70562ab1d6c92a4578608d54d9fad696e1dbdc00b2f4a0ce4114d01382` |
| `recovered-code/rerun-2026-09-26-prose-c05d54e7.json` | `ef04c650c23c1a43679bf6e0f148c75e19e6334e889433457772135f87a96d59` |
| `recovered-code/rerun-2026-09-26-prose-unplanned-246ffdb1.json` | `0bc63daa5117bedfc2698a89428af529e762bbb6eadf86dc87b3eac70aedca6d` |
| `recovered-code/rerun-2026-09-26-table-source-2adf1acc.json` | `b782c40c9df1f453d0965abadedf7f7af8a8aeee96fd4ad8a0b07fef6686a9ea` |
| `recovered-code/retention.py` | `018848f2ab24bd71ba81ffe03e0b30f70fed84c1719e4bc97352501fac1702bb` |
| `recovered-code/rollback-ct104-retention.py` | `8d365a2d0f5dd31265008ad8cc43d32b3f7b867883172fc21470881e28224788` |
| `recovered-code/rollback_code_publisher.py` | `f66aebbbaa264e2e5da100bf527f0a28fb4350d68dda0a62687861a656a827ca` |
| `recovered-code/safety-records-2026-09-30/live-30.json` | `36b8572cf9571dd4b33acc8f047a0444d0305bce1c55d78cb1f10cb953be036e` |
| `recovered-code/safety-records-2026-09-30/master-unit-tests.txt` | `e5a3b0f5ed5f3e51abfbe337238f752e7beffccdfe10d09c4406349a4ce33e17` |
| `recovered-code/safety-records-2026-09-30/measure.py` | `7674666eb167c90ec4a73c4560e35a3566dbd79054a9fdb3469937a7330ea6d5` |
| `recovered-code/safety-records-2026-09-30/production-tests.txt` | `af2748e76ead139244e289360c8784865d5d14b52daeae59b0594e6d5672b9b6` |
| `recovered-code/safety-records-2026-09-30/trap-events.json` | `bd65733cf0b0039937fd81f1ac9204c1e3ce222e5cc33bb75523cd101919cb60` |
| `recovered-code/safety-records-2026-09-30/traps.json` | `55a017e1005921d9fe943c0ed10df25cf02b1bb856743d682f77c79ff1a6dce7` |
| `recovered-code/safety-records-2026-09-30/unit-tests.txt` | `89fe507c5afadf7a15bc83bdeb4dfe41eabe224a0bccb5992fb3a600cc0b3f39` |
| `recovered-code/safety-records-2026-09-30/verification.json` | `500059dfbf85bdbc265fab107e9de6ff68a6c484db825d1e2ef53e17a4290f35` |
| `recovered-code/seven-reservoir-test.json` | `fb328509ca255f63b4405499631c91ef01528f0db564716f93fe038dbfb150df` |
| `recovered-code/signed-code-install-kit-2026-09-30/SHA256SUMS` | `2bc26795919aa7618b86891286dd77ddb465060baa225cb86ee6e34eb0aa8064` |
| `recovered-code/signed-code-install-kit-2026-09-30/code_publisher.py` | `72ccb4f68bc458beed6aef6dd10fbf946c5328e254ca77dcfdaa35719fe2bb8c` |
| `recovered-code/signed-code-install-kit-2026-09-30/code_release.py` | `ed664236c17e5a2289beeac22c59361b6bc6404034a5b3b1adc798fccebc4d57` |
| `recovered-code/signed-code-install-kit-2026-09-30/code_transport.py` | `459a141577d10ee602cd4d4d54dc13b46c89a8b63600308ee95247e35b6a19c8` |
| `recovered-code/signed-code-install-kit-2026-09-30/install-ct104-code.py` | `d8a345c9622bf594cda4f2e2be94e15c8607aed2699b3b3bbdfa51986d5a6245` |
| `recovered-code/signed-code-install-kit-2026-09-30/replication.py` | `902c4d633ea3db93cebe5448b626634a8ebf7d8c31e7a37d7a067cd1c61e10fa` |
| `recovered-code/signed-code-install-kit-2026-09-30/rollback-ct104-code.py` | `15f4d0bfb1da6bb2ba9252caec7a02188b81d434d23e5f78979135a4f56e2fa3` |
| `recovered-code/signed-code-install-kit-final-2026-09-30/SHA256SUMS` | `bad8498e4c4afe29891025f4232595ca3a2e7629d60f36ca3722faf429de58c0` |
| `recovered-code/signed-code-install-kit-final-2026-09-30/code_builder.py` | `b6f27fa2cb031df7c28b58f8f06b4c5ef89f3a954cec71300515202fe55f777b` |
| `recovered-code/signed-code-install-kit-final-2026-09-30/code_publisher.py` | `72ccb4f68bc458beed6aef6dd10fbf946c5328e254ca77dcfdaa35719fe2bb8c` |
| `recovered-code/signed-code-install-kit-final-2026-09-30/code_release.py` | `ed664236c17e5a2289beeac22c59361b6bc6404034a5b3b1adc798fccebc4d57` |
| `recovered-code/signed-code-install-kit-final-2026-09-30/code_transport.py` | `459a141577d10ee602cd4d4d54dc13b46c89a8b63600308ee95247e35b6a19c8` |
| `recovered-code/signed-code-install-kit-final-2026-09-30/install-ct104-code.py` | `d8a345c9622bf594cda4f2e2be94e15c8607aed2699b3b3bbdfa51986d5a6245` |
| `recovered-code/signed-code-install-kit-final-2026-09-30/replication.py` | `902c4d633ea3db93cebe5448b626634a8ebf7d8c31e7a37d7a067cd1c61e10fa` |
| `recovered-code/signed-code-install-kit-final-2026-09-30/rollback-ct104-code.py` | `15f4d0bfb1da6bb2ba9252caec7a02188b81d434d23e5f78979135a4f56e2fa3` |
| `recovered-code/signed-code-install-kit-v3-2026-09-30/SHA256SUMS` | `40c8a2cf9a3d0f69c927afb39bb47771da2314c422d902b2b5c953256f04487d` |
| `recovered-code/signed-code-install-kit-v3-2026-09-30/code_builder.py` | `b6f27fa2cb031df7c28b58f8f06b4c5ef89f3a954cec71300515202fe55f777b` |
| `recovered-code/signed-code-install-kit-v3-2026-09-30/code_publisher.py` | `fa708757d030530f93f81422e92255d8fd5da866a63b994c0739ef63645152b9` |
| `recovered-code/signed-code-install-kit-v3-2026-09-30/code_release.py` | `ed664236c17e5a2289beeac22c59361b6bc6404034a5b3b1adc798fccebc4d57` |
| `recovered-code/signed-code-install-kit-v3-2026-09-30/code_transport.py` | `459a141577d10ee602cd4d4d54dc13b46c89a8b63600308ee95247e35b6a19c8` |
| `recovered-code/signed-code-install-kit-v3-2026-09-30/install-ct104-code.py` | `ba13483983f8c27086332b5a7fbf19740824245d05c98ab511cfb7cef4b850c3` |
| `recovered-code/signed-code-install-kit-v3-2026-09-30/replication.py` | `902c4d633ea3db93cebe5448b626634a8ebf7d8c31e7a37d7a067cd1c61e10fa` |
| `recovered-code/signed-code-install-kit-v3-2026-09-30/retention.py` | `018848f2ab24bd71ba81ffe03e0b30f70fed84c1719e4bc97352501fac1702bb` |
| `recovered-code/signed-code-install-kit-v3-2026-09-30/rollback-ct104-code.py` | `f66aebbbaa264e2e5da100bf527f0a28fb4350d68dda0a62687861a656a827ca` |
| `recovered-code/signed-code-install-kit-v4-2026-09-30/SHA256SUMS` | `b5d1aa09095f4c2f6e44eaa0762d811908023d792f2866ee55134fab1b8abc53` |
| `recovered-code/signed-code-install-kit-v4-2026-09-30/code_builder.py` | `b6f27fa2cb031df7c28b58f8f06b4c5ef89f3a954cec71300515202fe55f777b` |
| `recovered-code/signed-code-install-kit-v4-2026-09-30/code_publisher.py` | `ba1ba5e88a87dcf72958b0a4f193a980cb3ab1eba0926526b99691d73579db1d` |
| `recovered-code/signed-code-install-kit-v4-2026-09-30/code_release.py` | `ed664236c17e5a2289beeac22c59361b6bc6404034a5b3b1adc798fccebc4d57` |
| `recovered-code/signed-code-install-kit-v4-2026-09-30/code_transport.py` | `459a141577d10ee602cd4d4d54dc13b46c89a8b63600308ee95247e35b6a19c8` |
| `recovered-code/signed-code-install-kit-v4-2026-09-30/install-ct104-code.py` | `c3b8b6903948d40a6842224f3fa60f2bb79d71526e36ce6f35afb5b0c7765cc5` |
| `recovered-code/signed-code-install-kit-v4-2026-09-30/replication.py` | `902c4d633ea3db93cebe5448b626634a8ebf7d8c31e7a37d7a067cd1c61e10fa` |
| `recovered-code/signed-code-install-kit-v4-2026-09-30/retention.py` | `018848f2ab24bd71ba81ffe03e0b30f70fed84c1719e4bc97352501fac1702bb` |
| `recovered-code/signed-code-install-kit-v4-2026-09-30/rollback-ct104-code.py` | `f66aebbbaa264e2e5da100bf527f0a28fb4350d68dda0a62687861a656a827ca` |
| `recovered-code/signed-code-records-2026-09-30/budget-hardened-full-suite.txt` | `299c0494b6daabe5fba333f64f0cc8b55d6761c0570335f5ac176e1cb30450cc` |
| `recovered-code/signed-code-records-2026-09-30/budget-hardened-local-tests.txt` | `44d9ce9a2c76d4b3031aab5319cb6dd7c435b0143146629668166eef9a1d6bff` |
| `recovered-code/signed-code-records-2026-09-30/full-suite-final.txt` | `ac4049f55b051fb5dbf15ad61f1c2d80198f8f9d871449f23e9c7f8da2a002b0` |
| `recovered-code/signed-code-records-2026-09-30/full-suite-verified.txt` | `5e7f6bc7634610ecd99ef304e35cec2acfeb3cf87d91a71779f9fee993cc773d` |
| `recovered-code/signed-code-records-2026-09-30/full-suite.txt` | `bcfc8a7d7f834e486d6a57050f602f0d3c4949eaa3b71e7a871ff6eb2a8877d5` |
| `recovered-code/signed-code-records-2026-09-30/handoff-full-suite.txt` | `952f548bb5fd4fb23570ffed62d44aecf037d7df08c1b395b9e61c605cb2bd21` |
| `recovered-code/signed-code-records-2026-09-30/handoff-local-tests.txt` | `98bea3809291acaaf34e3c3fd61eb6b6f5275f645def91b0cd1c614befebcd5b` |
| `recovered-code/signed-code-records-2026-09-30/local-failure-tests-final.txt` | `f6d6d84a43643da0cc4c67328a0cac40d539a9fe427cfe54f8b0282b10215505` |
| `recovered-code/signed-code-records-2026-09-30/local-failure-tests-verified.txt` | `bb23e75eafe841f59f751e5ec5d7692167d93a9e50985ab39a26d90bd264da3c` |
| `recovered-code/signed-code-records-2026-09-30/local-failure-tests.txt` | `11aeef5ca2c3d62d287e49bb52bbd2ccd7f19d6ddddb51f1505773f513cb5e10` |
| `recovered-code/signed-code-records-2026-09-30/release-full-suite.txt` | `59131e25f2fba372bd9768e42b7f29e667189f42befb0b6688215aed120aa56a` |
| `recovered-code/signed-code-records-2026-09-30/release-local-tests.txt` | `79eefe1fd768a8802d8dfaffa35d452f28b370c5584257c30b7cbbe8d695fe65` |
| `recovered-code/signed-code-records-2026-09-30/resumed-full-suite-2026-09-30.txt` | `93dec9094581078ad49ed5fd2598242aff79285f4504353fe492087becbc12d4` |
| `recovered-code/signed-code-records-2026-10-02/merged-full-suite.txt` | `384794702411980cb64fe74f75eebb180848dd489260e71d76d1efdaf4a4bd22` |
| `recovered-code/signed-code-records-2026-10-02/release-1-operator-report.md` | `bf654c2fec3c65172c87aa52e3029290cc79638626c2b3b927eb325940792088` |
| `recovered-code/signed-code-records-2026-10-02/release2-harness-fix-full-suite.txt` | `c8ea0ee90858e265988a79176293008e0dad2353ffd610c3e3784c2878f00b6f` |
| `recovered-code/source-memory-query-1.json` | `f3207bd7991b509b50b8b0f5c7a007eb83feb4db31175e89cbd85e55d55823d3` |
| `recovered-code/source-memory-query-2.json` | `d788acc6f0796f6509c377b2e598d43899a7cb623366dc891c2de293ab8d31d8` |
| `recovered-code/source-memory-validation.json` | `200a6c5b020adb7ffc731aab2616fcbf62231adcc0a7036d6d5ef9cf06b4a013` |
| `recovered-code/source-recovery-seeds-29-47-2026-09-27.json` | `2fb44206b7716dcd950af07b4da40b33f780568669ceeb7c820754460891a58a` |
| `recovered-code/source-recovery-validation-2026-09-27.json` | `650ed1ac774ec1e3d0594adf389a7501bfaf80d1d1b7149cb89ef382799bda6e` |
| `recovered-code/source_recovery.py` | `d26042d64cec97331de1a0902924987d1c23135a8631e23a0c0f507356625d15` |
| `recovered-code/structured-comparison-records-2026-09-28/after.json` | `38d49785a5cff6304dae6d1b797da6f7d91947270a9d3d48e160487053fff01b` |
| `recovered-code/structured-comparison-records-2026-09-28/before.json` | `5dfad71bbf3e34205124e47f9e0021876576d684aa314a4aef8deea79882b57f` |
| `recovered-code/structured-comparison-records-2026-09-28/measure.py` | `b992a78d41816273343490cd01c7bfc8eb3fe7082f2cd2ccb4a15777f1566904` |
| `recovered-code/structured-comparison-records-2026-09-28/mutations-initial.json` | `4696e81831aae715a35c5185d4bffa1706e699ae49a1827caba7e416e49e3da9` |
| `recovered-code/structured-comparison-records-2026-09-28/mutations.json` | `2c3b58057d9c2d727d65a366f1720ac4cace5d08350d42b23c0672e5a787eac3` |
| `recovered-code/structured-comparison-records-2026-09-28/mutations.py` | `1d7d71e74994493defc31da0264989dc0297fce89c2b823b7ca96433be203e79` |
| `recovered-code/structured-comparison-records-2026-09-28/policy-relevance-after.json` | `eb3a48b5a63925df85e236e6a4024e6147db63a4838c2a9ddd93ae222be9ba3e` |
| `recovered-code/structured-comparison-records-2026-09-28/policy-relevance-before.json` | `65fed54803b1264d96b5d970f3905d792b607824df6fd3e381865295c5b610dc` |
| `recovered-code/structured-comparison-records-2026-09-28/policy_relevance_diagnostic.py` | `1df80eb367700c32805f58a5f859f1ab2156ba6e42747d70b038e2bb533b576a` |
| `recovered-code/structured-comparison-records-2026-09-28/regression-before.txt` | `b17d524cfe87d2504fdb473e9a4c100ce14f80991849de248e31238aef86b65c` |
| `recovered-code/structured-comparison-records-2026-09-28/reported-pair-before.txt` | `942850d5d8a89190633cd19017a30e6f99ec932c85652c6d449974efa67e2254` |
| `recovered-code/structured-comparison-records-2026-09-28/saved-results-audit.json` | `1cc8d7778c7556d6b2e3a3a8da204b8956ff0b9d446839172394a240750787fa` |
| `recovered-code/structured-comparison-records-2026-09-28/tests.txt` | `0cd9dddddf757dd521f243abff7e3082c706657a236863059b05e2cf08c50ddd` |
| `recovered-code/structured-policy-complete-record.json` | `02a777a954f0df2fe7804667d48bdc5722a41546f96ff30674142aaff0030540` |
| `recovered-code/structured-policy-notfound-8f814944.json` | `ec30f83d6de5e16488f432c99ca22e6bb85f96e0220a2a6f372eaa659fbb85e4` |
| `recovered-code/structured-prose-diagnostic.json` | `3314082fb75669b876d08777214f29a16bc9d10a1e67f5beadbc29a49b902811` |
| `recovered-code/structured-prose-validation-baaeb1ee.json` | `a0c7fb456cceb53392f009c31a680be6c8065a8fa66639bd51383a38ab70ef9d` |
| `recovered-code/structured-table-validation-4a0208d6.json` | `98314d79b4212b54bd92074409655c451877761b6162bdc1aabad8bb46a36a46` |
| `recovered-code/support-meaning-rerun-4c9252b8.json` | `467212e9e5340a7e72b16404f7dc9e84b07af76af9df1025d316a7e5738060eb` |
| `recovered-code/support-seeded-0564edb2-adjudicated.json` | `abf3ef70d7f0d6e4da74630a1b68b196c3f1995372a74cd461479636182fcbe4` |
| `recovered-code/support-seeded-0564edb2-raw.json` | `f7daa22baae7c8d0ffa7608866b8da6026873bc0c99a3742a15e6e726f65e3a8` |
| `recovered-code/support_cookie.py` | `4bc590252ef0b322332b69b38866fecb7810818cb79b4f2a3cca577b77bc5b07` |
| `recovered-code/survivability-coverage-2026-09-27.json` | `d5c5b8c88cbec40fe0f56061580b7cb64251180907f2c394479db99542255560` |
| `recovered-code/survivability-step-1-2026-09-27.json` | `e6618d9149a16ad892d5c8af9f7cca0f467c28f18f3fd8c66ddcf5debef22594` |
| `recovered-code/sync_agent.py` | `4a82418c7d07e3550148048511462cb29aa67ac2dd681f7debffa773f363bb75` |
| `recovered-code/table-context-validation-40eddada.json` | `2af8a177ca84e58815c6752348c468bc8839df3b508ec975436837d24a6a39b6` |
| `recovered-code/test_code_recovery.py` | `7d0c9a370310199f7ed02bdd52a22ceb22f9bdf6f8c9825b71f8f30d21ee8316` |
| `recovered-code/test_code_sync_integration.py` | `90defd47173bf77412f0e242b6e3fb635a21d0c03c631e1f769e710461d3fbf0` |
| `recovered-code/test_cross_machine_recovery.py` | `f6fe1b119d50768571c1287bcdf515bd97bb9d8d7c926231044c9ad6d597337a` |
| `recovered-code/test_hive.py` | `8c61c990d5a291f053d6f72e15c11b3fd21d83a044c885b2b8c92de10265291b` |
| `recovered-code/test_knowledge.py` | `1bb1d027ab912cce4ba15e6a92963d988b79928ad30d6f99d392e3f26271a937` |
| `recovered-code/test_model_audit.py` | `d05b526ec12b091d605c9791d4ea57914dbe7a4e5c2c6ebbe2735c026ac38ba0` |
| `recovered-code/test_ollama_local.py` | `9b40fc91c6b6ed2682baad36aa1efd9bb6d62a7950aa593f1c62e00bfd1fa149` |
| `recovered-code/test_policy_binding.py` | `ccfc7704e562b8b35877caa392ccc2a92dda7b194a66c5ce36ec8fc921e7b88e` |
| `recovered-code/test_policy_lore.py` | `90beda42822ccba54f5f3496ae7a90d492c8374bdf8c9b188b6056aa1214b9cb` |
| `recovered-code/test_policy_slots.py` | `aee11aeba20bf0b24523f56bd9bc018c20b1442271415be929a67ef9c7e967fe` |
| `recovered-code/test_policy_tables.py` | `f479528b575345ce5b86ec73e77784b6113c707e4eb4665a4a26011e87701dfc` |
| `recovered-code/test_production_lore.py` | `d8604ce7266a579a535270b8d6ac609aee8fb6197b822c40f30c0c4ba6a001f3` |
| `recovered-code/test_relevance_cookie.py` | `2bbdf535caef1249af2752f7902503d9a213eb193fb997a80df0914071fa354d` |
| `recovered-code/test_replication.py` | `101fd816f841b3e1e984157ed0f214a1158fd90f6950c9d0a010d05a9dfca159` |
| `recovered-code/test_retention.py` | `8021293821a60809907dc56479983fd3b1ed4cd1b314cb9be7d6498645de9e93` |
| `recovered-code/test_source_recovery.py` | `68da7bc35a0a45d4d6409a2dd65e9d49236ce6a8ce2aed6c0237d0bafd3d85c1` |
| `recovered-code/test_support_evaluation.py` | `b952cd80c540c430462cc9411a74a4e375486b4bbef5f99faaef68e8d25cf068` |
| `recovered-code/test_sync_agent.py` | `f10fbc8097d4b49ddcdd5f64f86adb4d74d2bf0b3c40e9ba8dfb127bc0a70921` |
| `recovered-code/test_version_comparison.py` | `0932709545afd079ff765a9d5aad66984112f581954438f45b22316fd1686c25` |
| `recovered-code/update_ct104_recovery.py` | `c9a9cd1042958d652d0ac5ab72c99ec0c7a599cff38d637a666df0a8b539a480` |
| `recovered-code/upgrade_ollama_wsl_03214.sh` | `4b6b6839c76b9427fad6d0fa8581857683a82567dd12fbe9ff703c71e28427cb` |
| `recovered-code/validate_ct104_limits.py` | `89f73a2d04b80b5fe731b1a337102d31dc171232a97a6c2ff907349f465ca4ad` |
| `recovered-code/validate_ct104_live.py` | `4ffafd09d7c4c23d592982f0ee7cc5b7af9a6fc1bf847a8b51a303e1e9e06914` |
| `recovered-code/verifier-v2-validation.json` | `e7bde6eb00b9fbced6cafb559c09b703cfcb96cd9a34b6937fe5415eafe98993` |
| `recovered-code/version_comparison.py` | `f97fb81ca5ce2f53db4d63a31c81a4011ab5e2bbc65decfbc8cdd1fb1c908054` |

</details>
