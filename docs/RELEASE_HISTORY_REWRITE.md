# Release History Rewrite Plan

> Status: **prepared, awaiting owner execution + remote force-push
> approval**. The plan below is the trade-trace-ox5c deliverable.
> The local rewrite step is destructive (rewrites every commit
> hash in the repo) and the remote force-push step is destructive
> and shared (overwrites `origin/main`). Both are gated on
> explicit operator approval at execution time per the bead's
> safety boundary.

## Why we need to rewrite history

`trade-trace-piav` removed tracked `.beads/`, `audits/`, and
`docs/audits/` artifacts from HEAD. The files are still
reachable from prior commits — anyone who clones the repo can
see them via `git log -p` or `git show <old-sha>`. For a public
PyPI-targeted repo, the old commits must be unreachable so:

- Owner email and personal name strings disappear from the
  public history (currently 268+ matches across 276 files in
  pre-piav commits).
- `/home/hermes/code/trade-trace` absolute paths in audit
  artifacts disappear.
- The Beads metadata (`.beads/config.yaml`,
  `.beads/metadata.json`, etc.) is no longer carried in
  publicly-shipped history.

## Pre-flight checks

Run before the rewrite:

```bash
# 1. Confirm working tree is clean.
git status

# 2. Confirm you are on `main` and at the post-piav commit.
git log -1 --oneline   # expect "Remove .beads and audit artifacts ..."

# 3. Tag the pre-rewrite state. If anything goes wrong, this is
#    your recovery anchor.
git tag -a pre-public-rewrite -m "anchor before trade-trace-ox5c rewrite"
git push origin pre-public-rewrite   # off-site copy

# 4. Make sure git-filter-repo is installed.
pipx install git-filter-repo
# or: pip install --user git-filter-repo
git filter-repo --version
```

## The rewrite

`git filter-repo` is the recommended tool; `git filter-branch`
is deprecated and order-of-magnitude slower. The Python
implementation rewrites commits in a single pass and is safer
for repos this size (~160 commits, ~5 MB of blobs).

```bash
# Run from a FRESH CLONE per filter-repo's safety contract.
# DO NOT run this inside the working checkout; filter-repo
# refuses unless --force is passed, which we deliberately do
# not pass.
cd /tmp
git clone --no-local --mirror /home/hermes/code/trade-trace trade-trace-rewrite.git
cd trade-trace-rewrite.git

# 1. Strip artifact trees from every commit.
git filter-repo \
  --path .beads \
  --path audits \
  --path docs/audits \
  --invert-paths \
  --refs refs/heads/main

# 2. Replace personal email + name strings in every blob.
#    The replace-message file maps "<old>==><new>" per line.
cat > /tmp/replace-text.txt <<'EOF'
michaelcrescenzo@gmail.com==>noreply@example.com
Michael Crescenzo==>Trade Trace Maintainer
/home/hermes/code/trade-trace==><repo-root>
/home/hermes==><home>
EOF
git filter-repo --replace-text /tmp/replace-text.txt --refs refs/heads/main

# 3. (Optional) Strip the same strings from author/committer
#    metadata. `git filter-repo --mailmap` is the documented
#    path:
cat > /tmp/mailmap.txt <<'EOF'
Trade Trace Maintainer <noreply@example.com> Michael Crescenzo <michaelcrescenzo@gmail.com>
EOF
git filter-repo --mailmap /tmp/mailmap.txt --refs refs/heads/main
```

## Post-rewrite scans

The rewrite is only as good as its verification. Run **all**
of these against the rewritten mirror before considering the
rewrite acceptable:

```bash
cd /tmp/trade-trace-rewrite.git

# 1. No tracked beads/audit files at any point in history.
git log --all --diff-filter=A --name-only \
  -- '.beads/' 'audits/' 'docs/audits/' \
  | sort -u
# Expect: empty output.

# 2. No personal email in any blob, any commit.
git grep -E "michaelcrescenzo@gmail\.com" $(git rev-list --all)
# Expect: empty output. Note this is O(blobs * commits) and
# may take a minute on a 160-commit repo.

# 3. No personal name string in any blob.
git grep -nE "Michael Crescenzo" $(git rev-list --all) \
  | head -5
# Expect: empty output.

# 4. No /home/hermes path in any blob.
git grep -nE "/home/hermes" $(git rev-list --all) | head -5
# Expect: empty output.

# 5. Author / committer hygiene.
git log --all --format="%aN <%aE> | %cN <%cE>" | sort -u
# Expect: only the substituted maintainer identity.

# 6. Final scan with a tool that handles binary blobs.
#    `trufflehog filesystem` or `gitleaks detect` are both
#    acceptable. Document the tool + version in the gate
#    notes from trade-trace-a468.
gitleaks detect --source . --no-git --verbose
```

Record every command's output under
`docs/architecture/release-history-rewrite-scans.md` (this file
is the new artifact produced by this bead) before declaring
the rewrite complete.

## Pushing the rewrite to `origin`

The remote force-push is a **separate, owner-approved** step.
Before running it:

1. Confirm the rewrite scans in the previous section all came
   back clean.
2. Communicate the rewrite to every collaborator with a local
   clone. They will need to re-clone after the force-push.
3. Mirror-push a backup to a private remote first so the
   pre-rewrite history is recoverable.

```bash
# Backup the pre-rewrite remote.
git remote add backup git@github.com:mcrescenzo/trade-trace-pre-rewrite.git
git push --mirror backup

# Then, with explicit operator approval, force-push the
# rewritten mirror to origin.
git push --mirror --force origin
```

After the force-push:

```bash
# 4. Drop the working clone and re-clone from origin to
#    verify the rewrite landed cleanly.
cd /tmp
rm -rf trade-trace-postrewrite
git clone https://github.com/mcrescenzo/trade-trace.git trade-trace-postrewrite

# 5. Re-run the post-rewrite scans against the clone.
cd trade-trace-postrewrite
git log --all --diff-filter=A --name-only \
  -- '.beads/' 'audits/' 'docs/audits/' | sort -u
git grep -E "michaelcrescenzo@gmail\.com" $(git rev-list --all)
```

## Decision points the owner must approve

- [ ] Approve the `--path` exclusion set (`.beads`, `audits`,
      `docs/audits`).
- [ ] Approve the replacement map (email, name, absolute paths).
- [ ] Approve the author/committer mailmap substitution.
- [ ] Approve the remote force-push to `origin` after the local
      scans come back clean.
- [ ] Approve the deletion of the pre-rewrite tag once the
      rewrite is verified in production (or keep it
      indefinitely for forensic recovery).

## Why this bead does not execute the rewrite

The agent that prepared this plan deliberately did not run
`git filter-repo` or force-push for three reasons:

1. **Tool install** — `git filter-repo` is not in the project's
   base image; installing it would expand the agent's
   permission surface.
2. **Working-tree safety** — `filter-repo` mandates a fresh
   `--no-local --mirror` clone. Running it inside the active
   checkout violates that contract.
3. **Force-push is shared state** — overwriting `origin/main`
   is the kind of action CLAUDE.md flags as requiring explicit
   user confirmation. The plan above makes the action
   reviewable; the action itself is the operator's call.

When the operator runs the plan, the rewrite + scans should
take well under an hour on a developer laptop. The most common
failure mode is missing a path in the exclusion set; if a scan
finds residual artifacts, re-run `git filter-repo` with the
additional path and re-scan.
