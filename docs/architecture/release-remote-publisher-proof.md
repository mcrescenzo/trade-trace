# Remote Publisher Settings Proof

> Status: read-only remote inspection for `trade-trace-gcpp`.
> No GitHub or PyPI settings were changed, no tag was pushed, and no package
> was published.

## GitHub repository

| Check | Result |
|---|---|
| Repository | `mcrescenzo/trade-trace` |
| Visibility | public |
| Default branch | `main` |
| Remote URL | `https://github.com/mcrescenzo/trade-trace` |

## GitHub Actions publishing shape

Local workflow inspection of `.github/workflows/workflow.yml` found:

| Workflow property | Result |
|---|---|
| Publish workflow | `Publish to PyPI` at `.github/workflows/workflow.yml` |
| Trigger | `v*` tags |
| Job environment | `pypi` |
| OIDC permission | `id-token: write` on the publish job |
| Publisher action | `pypa/gh-action-pypi-publish@release/v1` |

This confirms the repository has the expected OIDC trusted-publishing workflow
shape locally.

## GitHub environment `pypi`

Read-only GitHub API inspection returned:

| Field | Result |
|---|---|
| Environment exists | yes |
| Environment name | `pypi` |
| `can_admins_bypass` | `true` |
| `protection_rules` | empty list |
| `deployment_branch_policy` | `null` |

Interpretation: the `pypi` environment exists, but it currently has no required
reviewers, wait timer, or branch/tag deployment policy exposed by the GitHub API
response. If release policy requires a protected PyPI environment, this setting
is not yet sufficient.

## PyPI project

Read-only PyPI JSON inspection of `https://pypi.org/pypi/trade-trace/json`
returned:

| Field | Result |
|---|---|
| Project exists | yes |
| Project name | `trade-trace` |
| Latest version | `0.0.1rc2` |
| Release count | 1 |
| Project URL | `https://pypi.org/project/trade-trace/` |

PyPI trusted-publisher bindings are account/project settings and were not
verifiable from the public JSON endpoint or the currently available local CLI
state. The binding still needs owner confirmation from PyPI project settings, or
an approved authenticated inspection path.

## Boundary

This proof is inspection-only. It does not approve publishing. Changing GitHub
environment protections, changing PyPI trusted-publisher settings, pushing a tag,
or publishing to PyPI remain separate owner-approved actions.
