# Remote Publisher Settings Proof

> Status: **decision document for trade-trace-gcpp** — remote inspection and
> approved GitHub environment configuration. GitHub `pypi` environment
> protection now permits automatic `main` branch post-release publication and
> `v*` tag publication; PyPI trusted-publisher binding still requires
> owner-side verification.

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
| Trigger | `main` branch pushes and `v*` tags |
| Job environment | `pypi` |
| OIDC permission | `id-token: write` on the publish job |
| Publisher action | `pypa/gh-action-pypi-publish@release/v1` |

This confirms the repository has the expected OIDC trusted-publishing workflow
shape locally.

## GitHub environment `pypi`

Initial read-only GitHub API inspection found the `pypi` environment existed but
had no protection rules. After owner approval, the environment was configured by
GitHub API with release protections. It was later updated for the owner-approved
risky auto-publish policy: `main` branch pushes may deploy to the `pypi`
environment without a required reviewer, while the existing `v*` tag policy is
preserved.

Final readback:

| Field | Result |
|---|---|
| Environment exists | yes |
| Environment name | `pypi` |
| `can_admins_bypass` | `false` |
| Required reviewers | none |
| `prevent_self_review` | n/a |
| `deployment_branch_policy` | `{protected_branches: false, custom_branch_policies: true}` |
| Custom deployment policy | branch `main`; tag pattern `v*` |

Interpretation: the GitHub `pypi` environment no longer requires explicit
reviewer approval for publish jobs. It restricts environment deployments to the
`main` branch and `v*` tags. Admins cannot bypass the remaining environment
protection rules.

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

This proof records the current approved GitHub settings: the `pypi` environment
has admin bypass disabled and custom deployment policies for the `main` branch
and `v*` tags. The required-reviewer gate was intentionally removed for the
owner-approved auto-publish policy. Changing PyPI trusted-publisher settings or
pushing a manual release tag remain separate owner-approved actions.
