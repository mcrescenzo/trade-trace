# Public History Strategy

> Status: **selected strategy is a clean public branch/export from current
> HEAD**. The destructive `git filter-repo` rewrite described later in this
> document is retained only as a historical alternative plan. It is **not**
> the chosen path for the current public release unless the owner explicitly
> changes strategy later.

For the current public release, publishable git history should be created as
a fresh single-commit public export/branch from the approved private HEAD.
This keeps private working history intact, avoids rewriting or force-pushing
`main`, and makes the public reachable history exactly the curated export
tree plus sanitized maintainer metadata.

The proof artifact for the current export candidate is
[`docs/architecture/release-public-export-proof.md`](architecture/release-public-export-proof.md).

## Why public history must be clean

`trade-trace-piav` removed tracked `.beads/`, `audits/`, and
`docs/audits/` artifacts from HEAD; `trade-trace-jr9b` also removes
generated `docs/reviews/` artifacts from public HEAD. The files are still
reachable from prior commits — anyone who clones the repo can
see them via `git log -p` or `git show <old-sha>`. For a public
PyPI-targeted repo, the old commits must be unreachable so:

- Owner email and personal name strings disappear from the
  public history (currently 268+ matches across 276 files in
  pre-piav commits).
- `LOCAL_REPO_PATH` absolute paths in audit
  artifacts disappear.
- The Beads metadata (`.beads/config.yaml`,
  `.beads/metadata.json`, etc.) is no longer carried in
  publicly-shipped history.

## Selected path: clean public export/branch

The selected release-hygiene path is:

1. Start from the approved private HEAD after HEAD-only scrub work.
2. Create a clean export tree with `git archive HEAD` or equivalent.
3. Initialize a fresh repository/branch from that tree.
4. Commit the export as a single public commit using sanitized maintainer
   identity, for example `Trade Trace Maintainer <noreply@example.com>`.
5. Run reachable-history scans against the export repository for excluded
   paths and private strings before any remote publication.
6. Only after separate explicit approval, push the public branch/export and
   later tag/publish the release candidate.

This path does **not** rewrite private `main`, does **not** force-push
`origin/main`, does **not** create a release tag, and does **not** upload to
PyPI as part of the export proof.

## Historical alternative: destructive rewrite plan, not selected

The following `git filter-repo` plan is preserved for context from the prior
rewrite-planning bead. It is not approved for the current release path unless
the owner explicitly replaces the clean export strategy with a destructive
history rewrite.

## Historical pre-flight checks

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
git clone --no-local --mirror LOCAL_REPO_PATH trade-trace-rewrite.git
cd trade-trace-rewrite.git

# 1. Strip artifact trees from every commit.
git filter-repo \
  --path .beads \
  --path audits \
  --path docs/audits \
  --path docs/reviews \
  --invert-paths \
  --refs refs/heads/main

# 2. Replace personal email + name strings in every blob.
#    The replace-message file maps "<old>==><new>" per line.
cat > /tmp/replace-text.txt <<'EOF'
OWNER_EMAIL==>noreply@example.com
OWNER_NAME==>Trade Trace Maintainer
LOCAL_REPO_PATH==><repo-root>
LOCAL_HOME==><home>
EOF
git filter-repo --replace-text /tmp/replace-text.txt --refs refs/heads/main

# 3. (Optional) Strip the same strings from author/committer
#    metadata. `git filter-repo --mailmap` is the documented
#    path:
cat > /tmp/mailmap.txt <<'EOF'
Trade Trace Maintainer <noreply@example.com> OWNER_NAME <OWNER_EMAIL>
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
  -- '.beads/' 'audits/' 'docs/audits/' 'docs/reviews/' \
  | sort -u
# Expect: empty output.

# 2. No personal email in any blob, any commit.
git grep -E "OWNER_EMAIL" $(git rev-list --all)
# Expect: empty output. Note this is O(blobs * commits) and
# may take a minute on a 160-commit repo.

# 3. No personal name string in any blob.
git grep -nE "OWNER_NAME" $(git rev-list --all) \
  | head -5
# Expect: empty output.

# 4. No LOCAL_HOME path in any blob.
git grep -nE "LOCAL_HOME" $(git rev-list --all) | head -5
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
  -- '.beads/' 'audits/' 'docs/audits/' 'docs/reviews/' | sort -u
git grep -E "OWNER_EMAIL" $(git rev-list --all)
```

## Decision points the owner must approve

- [ ] Approve the `--path` exclusion set (`.beads`, `audits`,
      `docs/audits`, `docs/reviews`).
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
