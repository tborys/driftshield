# Release runbook

Manual release path, written for the first release (v0.2.0) and reusable until
tag-push automation lands. Every step is auditable; the artefact is built by
CI, never on a laptop.

## 1. Prepare

- Version bumped in `driftshield/pyproject.toml` and a dated section in
  `CHANGELOG.md`, merged to `main` through the normal review gate.

## 2. Build the artefact in CI

- Run the `release-build` workflow (workflow_dispatch) on `main`.
- Download the `dist` artefact from the run. It contains the sdist and wheel.
- Sanity checks locally:
  - `python -m twine check dist/*`
  - `python -m zipfile -l dist/*.whl` — no unexpected files, no frontend
    build output, nothing outside the package.

## 3. PyPI (account holder only)

- First release only: confirm the account that owns the `driftshield` name
  and create a project-scoped API token.
- `python -m twine upload dist/*` with `__token__` auth.
- Verify: `pip install driftshield==<version>` in a clean venv, then
  `driftshield --help` shows the new flags and `pip show driftshield` reports
  the version.

## 4. Tag and record

- `git tag v<version> <release commit>` and push the tag.
- Create the GitHub release from the tag, body copied from the CHANGELOG
  section.

## 5. After the first release

- Move to tag-push automation with PyPI trusted publishing (no long-lived
  token) — tracked separately.
