# ci

One CI system for every personal repo. The steps live here once; each repo says *what* to
check through a mise task, so `mise run ci` on the Mac runs exactly what GitHub runs.

## Add a repo

1. In the repo's `mise.toml`, pin its tools and define the checks:

   ```toml
   [tools]
   node = "24"
   gitleaks = "8.30.1"

   [tasks.ci]
   description = "Run the same checks as CI"
   run = [
     "gitleaks git --redact --no-banner",
     "npm ci --no-audit --no-fund", "npm run lint", "npm test", "npm run build",
   ]
   ```

   The `gitleaks` line (a secret scanner) is recommended for every repo. Use `gitleaks git`, not
   `gitleaks dir`: `dir` ignores `.gitignore`, so it would flag your local `.env` and scan
   `node_modules/` that CI never sees. CI checks out one commit, so there it scans the current
   tree; locally it also scans history, which is stricter, never looser.

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

4. Set up the repo on GitHub:

   - **Ruleset on `main`** (Settings → Rules → Rulesets → New branch ruleset, target `main`):
     require a pull request; require the status check `ci / CI` (caller job id `ci` from step 2,
     then the shared job's name) with "Require branches to be up to date before merging"; block
     force pushes; restrict deletions. Don't require an approving
     review: PRs opened under your own `gh` login can't be approved by you, so they'd never merge.
   - **Dependabot** for the repo's own packages, with minor and patch updates grouped into one
     PR per ecosystem. `.github/dependabot.yml`:

     ```yaml
     version: 2
     updates:
       - package-ecosystem: npm          # or pip, uv, cargo, ...
         directory: /
         schedule:
           interval: weekly
         cooldown:
           default-days: 7               # let a bad release get yanked before it reaches you
         groups:
           minor-and-patch:
             update-types: [minor, patch]
     ```

     Majors still arrive one PR each, since they're the ones that break things.

Optional inputs: `task` (default `ci`) and `timeout-minutes` (default 15), passed with `with:`.

## What the shared job does

`.github/workflows/ci.yml`: checkout (no persisted token) → mise-action installs the repo's
tools with a pinned mise → cache uv/npm downloads keyed on lockfiles → `mise run <task>`.
Concurrency cancels superseded runs per repo, branch and event.

## Deploying to the Pi: `pi/`

`pi/ci-gated-update` deploys an app on the Pi only when the newest push run of its CI workflow
passed for the exact commit at the tip of its branch. A systemd timer checks every 5 minutes,
so the Pi pulls changes and GitHub never needs a way into the home network. It is aurora's
`deploy/pi/update.sh` with everything Aurora-specific moved into a per-app config: an optional
pre-deploy unit, build command, restart unit and health check. A failed build or health check
rolls back to the previous commit, records the bad SHA so it is never retried, and fires an alert.

Set up an app (on the Pi, as yourself):

```sh
git clone https://github.com/rishi-desai/ci ~/homelab/ci     # once; uses the existing gh login
cp ~/homelab/ci/pi/apps/aurora.conf.example ~/aurora.conf     # or write one for another app
~/homelab/ci/pi/install.sh aurora ~/aurora.conf
sudo systemctl start ci-gated-update@aurora && journalctl -u ci-gated-update@aurora -n 20
```

`install.sh` copies the config to `/etc/ci-gated-update/<app>.conf` (root-owned), installs the
shared `ci-gated-update@` units, allows exactly that app's restart/pre-deploy commands in
`/etc/sudoers.d/ci-gated-update-<app>`, disables the app's old updater (`REPLACES_TIMER`) and
enables `ci-gated-update@<app>.timer`. Pulling a newer `~/homelab/ci` changes nothing until you
re-run `install.sh`. An app needs CI first: without a passing push run, nothing deploys.

Rolling back Aurora to its own updater: `sudo systemctl disable --now ci-gated-update@aurora.timer
&& sudo systemctl enable --now aurora-update.timer`.

## Maintaining it

- Action SHAs are pinned here only; Dependabot proposes updates weekly.
- Callers use the moving tag `v1`. After a compatible change: `git tag -f v1 && git push -f origin v1`.
  A breaking change gets `v2`, and repos move over one at a time.
- This repo is public (it holds no secrets), so any repo can call the workflow and the Pi can
  clone it without credentials. If it ever goes private, set Settings → Actions → General →
  Access to "Accessible from repositories owned by the user", or callers fail with "workflow
  was not found".
- `mise run ci` here also runs zizmor (a security linter for GitHub Actions workflows) next to
  actionlint. Fix its findings; if one must stay, add `# zizmor: ignore[<rule>]` with the reason.
