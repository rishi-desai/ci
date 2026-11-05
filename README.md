# ci

One CI system for every personal repo. The steps live here once; each repo says *what* to
check through a mise task, so `mise run ci` on the Mac runs exactly what GitHub runs.

## Add a repo

1. In the repo's `mise.toml`, pin its tools and define the checks:

   ```toml
   [tools]
   node = "24"

   [tasks.ci]
   description = "Run the same checks as CI"
   run = ["npm ci --no-audit --no-fund", "npm run lint", "npm test", "npm run build"]
   ```

2. Add `.github/workflows/ci.yml`:

   ```yaml
   name: CI
   on:
     pull_request:
     push:
       branches: [main]
     workflow_dispatch:
   permissions:
     contents: read
   jobs:
     ci:
       uses: rishi-desai/ci/.github/workflows/ci.yml@v1
   ```

3. Run `mise run ci` locally; if it passes, CI will too.

Optional inputs: `task` (default `ci`) and `timeout-minutes` (default 15), passed with `with:`.

## What the shared job does

`.github/workflows/ci.yml`: checkout (no persisted token) → mise-action installs the repo's
tools with a pinned mise → cache uv/npm downloads keyed on lockfiles → `mise run <task>`.
Concurrency cancels superseded runs per repo, branch and event.

## Maintaining it

- Action SHAs are pinned here only; Dependabot proposes updates weekly.
- Callers use the moving tag `v1`. After a compatible change: `git tag -f v1 && git push -f origin v1`.
  A breaking change gets `v2`, and repos move over one at a time.
- This repo is private, so Settings → Actions → General → Access must be
  "Accessible from repositories owned by the user", or callers fail with "workflow was not found".
