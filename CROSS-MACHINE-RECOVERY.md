# Survivability step 4: recovery on a second machine from the replica

> **Historical runbook.** This is kept to document the recovery protocol. The recovery kit, its installers (`build_recovery_kit.py`, `install-replica-recovery.py`, `update_…_recovery.py`) and the phone trust sheets it refers to are host-specific and are not included in this public release. Placeholders such as `<replica-ip>` stand in for the original values. The drill outcome is in SURVIVABILITY-STEP4-ASSESSMENT-2026-09-28.md.

Preparation is implemented; the physical Mac-off drill has not run. Work is on `survivability-step-4` from master. Existing tags and records are unchanged. Run the replica commands below only on the replica.

## Trust values to retain on the phone

The build receipt supplies the exact archive, release, and bundle SHA-256 values and recovery-code commit ID. Also keep:

- Replica address: `<replica-ip>`; hostname: `replica-host`.
- Replica Ed25519 host fingerprint: `<replica-host-key-fingerprint>` (from the Mac's verified known-host entry; compare the value shown on the replica console below).
- Selected database SHA-256: `13911c3542a3f68ace538c9c21c42d0b5c45f0bb04b970742ec06bc962f8a025` (26 events, two supported findings and one confirmed not-found finding).
- Mac model digest: `c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb`; Ollama `0.32.14`, `gemma4:e4b`, Q4_K_M.

The archive checksum authenticates the bundled installer and contents. The separately recorded release and bundle checksums authenticate the files fetched from the replica during recovery. Do not obtain trusted checksums solely from the same unauthenticated download.

## Preparation — recovery machine (WSL)

```bash
install -d -m 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/hive_replica_recovery -C recovery-host-hive-recovery
cat ~/.ssh/hive_replica_recovery.pub
```

Choose a passphrase. Keep the private key on the recovery machine. Only the public key goes to the replica. Do not overwrite an existing key; if that pathname already exists, stop and use a separately reviewed new filename.

## Preparation — Mac Terminal

The kit contains code and metadata, **no knowledge database**. This temporary server exposes only the kit directory. The Mac may serve these preparation files while alive; it must be shut down before the recovery phase.

```bash
python3 -m http.server 8765 --bind <lan-ip> \
  --directory '<workspace>/outputs/hive-recovery-kit-2026-09-27'
```

Leave that terminal open only until the replica finishes downloading, then press Ctrl-C. If the Mac's LAN address changed, update this bind address and the download address used on the replica together. Never serve the workspace or `.ssh` directory.

## Preparation — replica root console

1. Verify the target and independently record its host fingerprint:

```bash
hostname
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Require `replica-host` and the fingerprint above.

2. Install the minimal extra utilities used to verify bundles and grant narrow read access:

```bash
apt-get update
apt-get install --no-install-recommends git acl curl ca-certificates
```

No model, Ollama, or background application service is installed.

3. Download the kit. Replace `KIT_ARCHIVE_SHA256_FROM_PHONE` with the build receipt's exact value; do not run with the placeholder:

```bash
mkdir -m 700 /root/hive-recovery-kit
cd /root/hive-recovery-kit
curl --fail --show-error --output hive-recovery-kit.tar.gz \
  http://<lan-ip>:8765/hive-recovery-kit.tar.gz
printf '%s  %s\n' 'KIT_ARCHIVE_SHA256_FROM_PHONE' hive-recovery-kit.tar.gz | sha256sum -c -
```

Proceed only after `OK`:

```bash
tar -xzf hive-recovery-kit.tar.gz
sha256sum -c SHA256SUMS
```

4. Paste the recovery machine's public key (not its private key):

```bash
cat > /root/recovery-host-hive-recovery.pub <<'KEY'
PASTE_RECOVERY_MACHINE_ED25519_PUBLIC_KEY_HERE
KEY
ssh-keygen -lf /root/recovery-host-hive-recovery.pub
```

5. Install:

```bash
python3 /root/hive-recovery-kit/install-replica-recovery.py \
  --public-key /root/recovery-host-hive-recovery.pub \
  --kit /root/hive-recovery-kit
```

The installer checks hostname, root identity, bundle checksum/completeness, selected commit ref, checkpoint pin, schema/history/hash, total 2 GiB budget, and 1 GiB free-space reserve. Under the receiver lock, it exports the memory **from the replica's retained generation**, then verifies a read-back of the export. It creates a new locked-password account with a root-owned home and forced-command key. No shell/forwarding/PTY/user RC is permitted by the key restriction. It rejects reuse of the replica/root key. No existing SSH keys, receiver config, or history are changed; no SSH reload is needed.

Export: `/var/lib/hive-replica/recovery-export/`, root-owned; recovery account has read-only ACL access. The existing replica user can read the export for combined storage-budget accounting, but the recovery account cannot traverse other replica subdirectories. Code: `/usr/local/lib/hive-recovery/`. Account home/key: `/var/lib/hive-recovery/.ssh/authorized_keys`, root-owned.

Expected final lines:

```text
Recovery export installed; no SSH reload, key reuse, model, or production-history changes.
Verify SSH access from the recovery machine before powering off the Mac.
```

Any traceback or missing final line means setup is not verified. Preserve the console output and leave the Mac on for diagnosis. A partial install must be reviewed/removed before retrying; the installer refuses to overwrite an existing account/export.

## Preparation — recovery machine (WSL): verify restricted access

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/hive_replica_recovery
ssh -T -i ~/.ssh/hive_replica_recovery -o IdentitiesOnly=yes \
  -o HostKeyAlgorithms=ssh-ed25519 -o StrictHostKeyChecking=ask \
  hive-recovery@<replica-ip> status
```

Compare the displayed host fingerprint against the value recorded on your phone or shown on the replica console before accepting it. Define:

```bash
hive_remote() {
  ssh -T -i ~/.ssh/hive_replica_recovery -o IdentitiesOnly=yes \
    -o HostKeyAlgorithms=ssh-ed25519 -o StrictHostKeyChecking=yes \
    hive-recovery@<replica-ip> "$@"
}
hive_remote status
hive_remote push
hive_remote 'test status'
hive_remote 'fetch ../../etc/passwd'
hive_remote sh
```

Only `status` succeeds. Every other command must return nonzero with `Recovery refused`. Do not proceed if an unexpected command succeeds. Save this output. The allowed data commands are `release`, `code`, `status`, and `fetch` of the selected checkpoint only.

## Preparation — recovery machine model/GPU

First inspect any existing Windows/WSL Ollama to avoid starting two servers. Preferred runtime is Ollama inside WSL, managed by systemd, on loopback `127.0.0.1:11434`.

Windows PowerShell:

```powershell
wsl --version
wsl --list --verbose
nvidia-smi
```

WSL:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends python3 git openssh-client curl ca-certificates
nvidia-smi
systemctl status ollama --no-pager
ollama --version
```

If Ollama is absent, install the baseline release; don't replace an existing installation blindly:

```bash
curl --fail --show-error --location https://ollama.com/install.sh -o /tmp/hive-ollama-install.sh
OLLAMA_VERSION=0.32.14 sh /tmp/hive-ollama-install.sh
sudo systemctl enable --now ollama
```

If systemd is not available in this WSL distribution, stop for that setup rather than using nohup. WSL uses the Windows NVIDIA driver; do not install a Linux display driver. No CUDA development toolkit is required just to run Ollama.

```bash
ollama pull gemma4:e4b
ollama show gemma4:e4b
curl --fail http://127.0.0.1:11434/api/tags
```

The runner records the full actual model digest and Ollama version. A different digest **does not stop the drill**: it runs all nine trials under `model-change`, with `same_model_result` explicitly `not run`. A matching digest is `same-model`; hardware/runtime differences are still recorded. No retagging or altered seeds to hide differences. GPU use is checked through Ollama's `size_vram` after queries; partial offload is recorded, not claimed as full GPU residency. The current Mac model download is ~9.6 GB, so do not assume it fits entirely in the RTX 3070 VRAM.

## Recovery cutoff

Stop the temporary Mac server. Record the selected checkpoint, timestamp, and Mac-off start time on your phone. Power off the Mac. From this point until the report is complete, no Mac data, network shares, source copies, or Mac Ollama may be used. External package/model downloads are allowed; hive memory comes only from the replica. Do not reconnect the Mac to finish missing preparation.

## Recovery — recovery machine (WSL) only

Use a new directory on the Linux filesystem, not `/mnt/c` and not an old hive checkout:

```bash
mkdir -m 700 ~/hive-mac-died-drill
cd ~/hive-mac-died-drill
```

If starting a new shell, redefine `hive_remote` and unlock the recovery key using the preparation commands above. Download fresh code/metadata from the replica:

```bash
hive_remote release > release.json
hive_remote code > hive-recovery.bundle
printf '%s  %s\n' 'RELEASE_SHA256_FROM_PHONE' release.json | sha256sum -c -
printf '%s  %s\n' 'BUNDLE_SHA256_FROM_PHONE' hive-recovery.bundle | sha256sum -c -
```

Require both `OK`; replace placeholders from the phone, never just trust downloaded hashes. Then:

```bash
git init bundle-check
git -C bundle-check bundle verify ../hive-recovery.bundle
git clone hive-recovery.bundle hive-code
hive_code_commit=$(python3 -c 'import json; print(json.load(open("release.json"))["code_commit"])')
git -C hive-code checkout --detach "$hive_code_commit"
git -C hive-code rev-parse HEAD
```

Compare the printed commit to the phone's commit. Run the drill:

```bash
python3 hive-code/cross_machine_recovery.py \
  --release release.json \
  --remote hive-recovery@<replica-ip> \
  --key ~/.ssh/hive_replica_recovery \
  --destination recovered \
  --model gemma4:e4b \
  --seeds 11 29 47 \
  --temperature 0.2 \
  --report recovery-results.json
```

This command fetches memory itself from the replica, refuses existing destination/report paths, and keeps `recovered/pristine.sqlite3` byte-identical while querying a separate working database. Original source reads are blocked during every trial. Answers must be withheld before source recreation. The runner verifies restored evidence/support links, recreates and hashes sources, asks all nine trials, records raw model events/options, checks GPU use, and runs the full unit suite. Errors and mismatches stay in the report, with no automatic retries. All-question withholding cannot pass.

```bash
python3 - <<'PY'
import json
r=json.load(open('recovery-results.json'))
for k in ('status','classification','same_model_result','model_change_result','counts','byte_identical','gpu_acceleration_observed'):
    print(k, r.get(k))
PY
sha256sum recovered/pristine.sqlite3
```

Expected: nine correct, zero false accepts/rejects/errors; two original supported findings and one confirmed not-found preserved; six supported answers and three confirmed not-found new results; unit suite exit zero. `needs_review` is the correct *answer text* to the calculation-disagreement policy question, not the query status. Normalized answer differences that don't match baseline are recorded conservatively and need review; no model judge or loosened support check is used.

Save the complete JSON report and any failed attempt under unique names. A later same-model rerun uses a fresh destination/report; it never overwrites the model-change result. The Mac-off claim also requires the operator's cutoff observation; software cannot prove a remote computer was physically powered off.

## Rollback of recovery-only setup — replica root console

This removes only the new recovery account/export; it leaves production replication intact. Use after checking no recovery download is active. First remove its authorized key to prevent new sessions:

```bash
rm -f /var/lib/hive-recovery/.ssh/authorized_keys
pgrep -u hive-recovery
```

If processes are listed, wait for them to finish before continuing. Then:

```bash
setfacl --restore=/usr/local/lib/hive-recovery/setup-backups/store.acl
userdel hive-recovery
rm -rf /var/lib/hive-recovery
rm -rf /var/lib/hive-replica/recovery-export
rm -rf /usr/local/lib/hive-recovery
```

Preserve any root-console failure output before cleanup. No SSH reload is needed. The downloaded root kit may be retained as an audit copy or removed separately. An account/export that was only partially created requires checking which paths exist before these cleanup commands. Never remove `/var/lib/hive-replica` itself.
