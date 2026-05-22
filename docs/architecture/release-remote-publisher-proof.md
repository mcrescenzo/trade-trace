# Remote Publisher Settings Proof

> Status: **decision document for trade-trace-gcpp** — remote inspection and
> approved GitHub environment configuration. GitHub `pypi` environment
> protection was changed after owner approval; PyPI trusted-publisher binding
> still requires owner-side verification.

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

Initial read-only GitHub API inspection found the `pypi` environment existed but
had no protection rules. After owner approval, the environment was configured by
GitHub API with release protections.

Final readback:

| Field | Result |
|---|---|
| Environment exists | yes |
| Environment name | `pypi` |
| `can_admins_bypass` | `false` |
| Required reviewers | `mcrescenzo` user reviewer |
| `prevent_self_review` | `false` |
| `deployment_branch_policy` | `{protected_branches: false, custom_branch_policies: true}` |
| Custom deployment policy | tag pattern `v*` only |

Interpretation: the GitHub `pypi` environment now requires an explicit reviewer
approval for publish jobs and restricts environment deployments to `v*` tags.
Admins cannot bypass the environment protection rules.

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

This proof records one approved GitHub settings change: the `pypi` environment
now has reviewer protection, admin bypass disabled, and a `v*` tag deployment
policy. It does not approve publishing. Changing PyPI trusted-publisher settings,
pushing a tag, or publishing to PyPI remain separate owner-approved actions.
