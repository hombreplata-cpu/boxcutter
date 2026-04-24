# BUILD_LOOP — BoxCutter

This document defines the standard loop for planning, implementing, and shipping
changes to this repo. Follow it every session.

---

## The Loop

```
plan → implement → CI pre-flight → push → open PR → watch CI → fix → merge
```

---

## Step 1: Plan

- Read `CONTEXT.md` for current project state before writing any code.
- For non-trivial changes, write a plan and get approval before implementing.
- All plans are numbered sequentially: `PLAN_004`, `PLAN_005`, etc.
- Store plans in `docs/` or as Claude plan files — not in `main`.

---

## Step 2: Implement

- Always work on a feature branch: `git checkout -b feature/description`
- Never commit directly to `main` — branch protection is enforced on the remote.
- Make commits as logical units. Commit message format:
  ```
  Short imperative summary (≤72 chars)

  Optional body explaining why, not what.
  ```

---

## Step 3: CI Pre-flight (run before every `git push`)

Simulate what GitHub Actions will run. Fix all failures locally before pushing.
A push that fails CI creates noise — pre-flight catches it first.

### 3a. Lint (mirrors the `Lint (Ruff)` job)

```bash
ruff check . --output-format github
ruff format --check .
```

**Fix lint failures:**
- `ruff format .` — auto-fixes formatting
- `ruff check . --fix` — auto-fixes safe lint violations
- For remaining violations: fix manually or suppress with `# noqa EXXX  # reason`

### 3b. Security (mirrors the `Security (pip-audit + Bandit)` job)

```bash
pip-audit -r requirements.txt --progress-spinner off
bandit -r . -ll
```

**Fix security failures:**
- `pip-audit` CVE: bump the affected package floor in `requirements.txt`
- `bandit` finding: fix the code, or add `# nosec BXXX  # reason` if a confirmed false positive

### 3c. Syntax check (mirrors the `Build` job — Windows PowerShell)

```powershell
Get-ChildItem -Recurse -Filter "*.py" | ForEach-Object {
    python -m py_compile $_.FullName
    if ($LASTEXITCODE -ne 0) { Write-Error "Syntax error: $($_.FullName)"; exit 1 }
}
```

Or on bash (Git Bash / Linux):
```bash
find . -name "*.py" -not -path "./.venv/*" | xargs -I{} python -m py_compile {}
```

**All three checks must pass before pushing.**

---

## Step 4: Push and Open PR

```bash
git push origin feature/description
# Then open a PR on GitHub targeting main
```

PR title format: short imperative, ≤70 chars.
PR body: what changed and why. Link to the plan doc if one exists.

---

## Step 5: Watch CI

After opening the PR, monitor GitHub Actions. Do not declare the PR ready until
all three required status checks are green:

| Check name | What it tests |
|---|---|
| `Lint (Ruff)` | Style, unused imports, formatting |
| `Security (pip-audit + Bandit)` | Dependency CVEs + code security |
| `Build (install + syntax check)` | Packages install on Windows, all .py files compile |

If a check fails: read the full error, fix in a new commit, push — CI re-runs automatically.

---

## Step 6: Merge

Once all checks are green, merge via the GitHub PR UI (squash or merge commit — 
your choice). Delete the feature branch after merging.

Update `CONTEXT.md` with any new state after significant changes.

---

## Tools Required Locally

```bash
pip install ruff pip-audit "bandit[toml]"
```

These are dev dependencies — not in `requirements.txt` (which is for the app only).

---

## CI Pipeline Reference

Defined in `.github/workflows/ci.yml`. Three parallel jobs:

| Job | Runner | Tools |
|---|---|---|
| Lint | ubuntu-latest | ruff 0.4.4 |
| Security | ubuntu-latest | pip-audit 2.7.3, bandit 1.7.8 |
| Build | windows-latest | pip --no-deps, py_compile |

Dependabot opens weekly PRs for dep updates (Monday 9am ET). Each Dependabot PR
runs the full pipeline before you merge it.

### Bandit triage mode

Bandit currently runs with `--exit-zero` (reports findings, doesn't fail the job).
Once all existing findings are resolved or suppressed with `# nosec`, remove
`--exit-zero` from `ci.yml` to harden it into a hard gate.
