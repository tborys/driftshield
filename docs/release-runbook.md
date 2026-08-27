# Release runbook

How a `driftshield` release is cut. The artefact is always built by CI, never
on a laptop. The first release (v0.2.0) uploads to PyPI by hand because the
PyPI project does not exist yet; every release after that is a tag push.

## 1. Prepare the release PR

- Bump `version` in `driftshield/pyproject.toml` and `__version__` in
  `driftshield/src/driftshield/__init__.py`. They must match; the publish
  workflow refuses a tag that does not equal the package version.
- Add a dated `## <version> - YYYY-MM-DD` section at the top of
  `CHANGELOG.md`, written for users. The GitHub release body is cut from this
  section verbatim, so it has to stand on its own.
- Merge through the normal review gate. CI must be green.

## 2. Build and check the artefact in CI

- Run the `release-build` workflow (`workflow_dispatch`) on `main`.
- The workflow builds the sdist and wheel, runs `twine check`, asserts the
  wheel contains only the `driftshield` package, installs the wheel into a
  fresh venv and checks `driftshield --help` lists `analyze` and `submit`.
- Download the `dist` artefact from the run.

The same build and smoke test run again inside the tag push workflow, so a
green `release-build` run is the signal that the tag is safe to push.

## 3. First release only: manual PyPI upload

Done by the PyPI account holder, once, because trusted publishing can only be
configured for a project that already exists on PyPI (or via a pending
publisher, see below).

- `python -m pip install twine`
- `python -m twine check dist/*`
- `python -m twine upload dist/*` with `__token__` and a project scoped API
  token. Delete the token afterwards; it is not needed again.
- Verify in a clean venv: `pip install driftshield==0.2.0`, then
  `driftshield --version` prints `driftshield 0.2.0` and
  `driftshield --help` lists `analyze` and `submit`.

Then set up trusted publishing so the next release is automatic:

- On PyPI, open the `driftshield` project, Publishing, and add a GitHub
  publisher: owner `tborys`, repository `driftshield`, workflow
  `release-publish.yml`, environment `pypi`.
- On GitHub, create the `pypi` environment (Settings, Environments) and add
  the account holder as a required reviewer. The publish job pauses there
  until approved.

Alternatively, add a pending publisher on PyPI before the first release with
the same settings. Then the first release can use the automated path too and
this section is skipped.

## 4. Tag and release

- Tag the merged release commit on `main`: `git tag v0.2.0 <sha>` and
  `git push origin v0.2.0`. The tag must be `v` plus the package version.
- The tag push runs `release-publish`:
  1. `build`: builds, checks and smoke tests the artefact and asserts the tag
     matches `pyproject.toml`.
  2. `publish`: uploads to PyPI via trusted publishing (OIDC, no stored
     token). Runs in the `pypi` environment, so it waits for reviewer
     approval.
  3. `github-release`: creates the GitHub release with the CHANGELOG section
     as the body and the sdist and wheel attached.
- For the first release, where PyPI was uploaded by hand in step 3, the
  `publish` job will fail on the duplicate upload unless `skip-existing` is
  left on (it is). The GitHub release step still runs.

## 5. Verify

- `pip install driftshield==<version>` in a clean venv.
- `driftshield --version` reports the version.
- The GitHub release exists with the right notes and both files attached.

## Subsequent releases

Steps 1, 4 and 5 only. Step 2 is optional (the publish workflow repeats it)
and step 3 never repeats.
