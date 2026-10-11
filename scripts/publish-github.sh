#!/usr/bin/env bash
# Optional export to a new private GitHub repository, from an authenticated workstation.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
command -v gh >/dev/null || { echo 'Install GitHub CLI and run gh auth login first.' >&2; exit 1; }
gh auth status >/dev/null
repo=${1:-"$(gh api user --jq .login)/sovereign-federation-lab"}
git rev-parse --verify HEAD >/dev/null || { echo 'Clone the supplied Git bundle or commit the source first.' >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo 'Commit or remove local changes before publishing.' >&2; exit 1; }
if gh repo view "$repo" >/dev/null 2>&1; then echo 'Repository already exists; refusing to overwrite or change visibility.' >&2; exit 1; fi
if git remote get-url github >/dev/null 2>&1; then echo 'A github remote already exists; inspect it before retrying.' >&2; exit 1; fi
gh repo create "$repo" --private --description 'Sovereign Federation Lab: CockroachDB, OPA, OTel, ADRs and container development harness' --source . --remote github --push
[ "$(gh repo view "$repo" --json visibility --jq .visibility)" = PRIVATE ] || { echo 'Private visibility verification failed.' >&2; exit 1; }
gh repo view "$repo" --json url --jq .url
