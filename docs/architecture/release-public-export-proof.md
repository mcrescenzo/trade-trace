# Public Export Proof

> Status: proof for the selected clean public branch/export strategy for
> `trade-trace-5rrw`. This document records a local-only export candidate;
> no branch was pushed, no tag was created, no package was published, and no
> private history was rewritten.

## Candidate

- Private base HEAD: `a2c33125c20c87a06edcf9736d21eca662ab50fc`
- Exported tree: base HEAD plus the release-doc/proof updates from
  `trade-trace-5rrw` before they were committed on private `main`.
- Export repository: `/tmp/trade-trace-public-export-a2c33125c20c`
- Export commit: `9e5ccfb2f38cd5eb05e83cbc8ba81fac8144dce4`
- Export identity: `Trade Trace Maintainer <noreply@example.com>`
- Strategy: fresh single-commit public export/branch from an approved private
  tree, using a clean working tree export and reachable-history scans.

## Commands and results

| Check | Command | Result |
|---|---|---|
| Main tracked audit/review dirs | `git ls-files docs/audits docs/reviews` | empty |
| Export path history | `git log --all --diff-filter=A --name-only -- '.beads/' 'audits/' 'docs/audits/' 'docs/reviews/' \| sort -u` | empty |
| Export local home string | `git grep -nF -- '<local-home-path>' $(git rev-list --all)` | no matches, exit 1 |
| Export owner email string | `git grep -nF -- '<owner-email>' $(git rev-list --all)` | no matches, exit 1 |
| Export owner name string | `git grep -nF -- '<owner-name>' $(git rev-list --all)` | no matches, exit 1 |
| Export metadata identity | `git log --all --format='%H %an <%ae> \| %cn <%ce>'` | one commit with `Trade Trace Maintainer <noreply@example.com>` as author and committer |

## Boundary

This proof does not approve any public side effect. Pushing the export or a
public branch, pushing a release tag, and publishing to PyPI remain separate
operator-approved actions for the exact candidate SHA.
