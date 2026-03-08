---
name: pr-reviewer
description: Review pull requests for code quality, security, and correctness. Use on new PRs or when asked to review code changes. Supports automated CI integration via GitHub Actions.
---

# PR Reviewer

Automated pull request reviewer that checks code quality, security, and correctness.

## When to use

- When a new pull request is opened or updated
- When manually asked to review a PR
- As part of CI pipeline on pull_request events

## How to run

**Review a specific PR by number:**
```bash
bash skills/pr-reviewer/scripts/review.sh <pr-number>
```

**Review the current branch diff against main:**
```bash
bash skills/pr-reviewer/scripts/review.sh
```

The script performs the following checks:

1. **Diff analysis** - Fetches the PR diff and analyzes changed files
2. **Security scan** - Checks for common security anti-patterns (hardcoded secrets, SQL injection, XSS vectors, command injection)
3. **Quality checks** - Detects debug artifacts, large files, merge conflict markers, and TODO/FIXME annotations
4. **Test coverage signal** - Flags PRs that modify source code without corresponding test changes
5. **Dependency review** - Flags changes to dependency files (package.json, pyproject.toml, requirements.txt)

## Output

The script prints a structured review report to stdout and exits with:
- **0** if no critical issues found
- **1** if critical issues were detected (security findings or merge conflicts)

Example output:
```
== PR Review Report ==
PR: #42 - Add user authentication
Files changed: 8
Insertions: +245, Deletions: -12

[PASS] No merge conflict markers found
[WARN] Security: possible hardcoded token in src/auth.py:23
[WARN] No test files modified (source files changed: 5)
[INFO] Dependency file changed: package.json
[PASS] No excessively large files added

Summary: 0 critical, 2 warnings, 1 info
```

## GitHub Actions integration

The workflow `.github/workflows/pr-review.yml` runs this skill automatically on every pull request. Review results are posted as a PR comment.

## Checks performed

| Check | Severity | Description |
|-------|----------|-------------|
| Merge conflict markers | Critical | Git conflict markers (`<` / `=` / `>` repeated 7 times) in code |
| Hardcoded secrets | Warning | API keys, tokens, passwords in source |
| Debug statements | Warning | `console.log`, `print(`, `debugger`, `binding.pry` |
| Large file additions | Warning | New files exceeding 500KB |
| Missing test changes | Info | Source changed without test changes |
| Dependency changes | Info | Lock file or manifest modified |
| TODO/FIXME markers | Info | New TODO or FIXME comments added |
