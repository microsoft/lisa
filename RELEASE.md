# Releasing `mslisa` to PyPI

LISA is published to PyPI as the [`mslisa`](https://pypi.org/project/mslisa/)
package. Releases are driven by the
[`publish.yml`](.github/workflows/publish.yml) workflow and use **PyPI Trusted
Publishing (OIDC)** — no API tokens are stored anywhere.

End user install:

```bash
pip install mslisa            # core only
pip install "mslisa[azure]"   # most common: with Azure SDK extras
pip install "mslisa[azure,libvirt]"
lisa --help
```

---

## One-time bootstrap (do once per project / per environment)

These steps are needed before the first successful release. After bootstrap they
do not need to be repeated.

### 1. PyPI pending publishers

Any maintainer signs in to PyPI **and** TestPyPI with their personal account
(2FA required), then adds a **pending publisher**:

- PyPI → <https://pypi.org/manage/account/publishing/> → *Add a new pending publisher*
  - PyPI Project Name: `mslisa`
  - Owner: `microsoft`
  - Repository name: `lisa`
  - Workflow name: `publish.yml`
  - Environment name: `pypi`
- TestPyPI → <https://test.pypi.org/manage/account/publishing/> → same form, but
  - Environment name: `testpypi`

The first successful workflow run claims the project name automatically. After
that the personal account can be removed from the project; the trust is bound
to `microsoft/lisa` + `publish.yml`, not to the person.

### 2. GitHub Environments

In `microsoft/lisa` → **Settings → Environments**, create two environments:

| Environment | Required reviewers | Purpose |
|---|---|---|
| `testpypi`  | (none, optional)   | Auto-publishes pre-release artifacts |
| `pypi`      | 1–2 LSG maintainers | Human approval gate before PyPI |

Reviewers approve via the Actions run UI when the workflow pauses on the `pypi`
environment.

### 3. Tag protection (recommended)

**Settings → Tags → Add rule** → pattern `2[0-9][0-9][0-9][0-9][0-9][0-9][0-9].*`,
restrict push to release managers. Prevents accidental tag-based releases.

---

## Cutting a release

LISA uses **CalVer** tags in the form `YYYYMMDD.N` (e.g. `20260420.1`,
`20260420.2`). `setuptools_scm` derives the package version directly from the
tag, so the PyPI version equals the tag (no `v` prefix).

1. Make sure `main` is green.
2. Pick today's date and the next sequence number for that day.
3. Update `CHANGELOG.md` (or release notes draft) and merge.
4. Tag and push:
   ```bash
   git checkout main
   git pull --ff-only
   TAG=$(date +%Y%m%d).1          # bump .1 -> .2 if a tag for today exists
   git tag -a "$TAG" -m "$TAG"
   git push origin "$TAG"
   ```
5. Watch **Actions → Publish to PyPI**.
6. After the `publish-testpypi` job succeeds, smoke test in a clean venv:
   ```powershell
   $TAG = "20260513.1"   # use the tag you just pushed
   py -3.12 -m venv C:\tmp\mslisa-rc
   & C:\tmp\mslisa-rc\Scripts\python.exe -m pip install `
       --index-url https://test.pypi.org/simple/ `
       --extra-index-url https://pypi.org/simple/ `
       "mslisa[azure]==$TAG"
   & C:\tmp\mslisa-rc\Scripts\lisa.exe --help
   ```
7. Approve the `pypi` environment in the workflow run.
8. Verify the live release:
   ```bash
   pip install --upgrade "mslisa==20260513.1"
   lisa --version
   ```

> A version that has been uploaded to PyPI **cannot** be replaced. To fix a bad
> release, yank it on PyPI and publish a new patch version.

---

## Local dry run (no upload)

Use this any time you change packaging metadata, `MANIFEST.in`, or
`pyproject.toml`:

```powershell
cd lisa
.\.venv\Scripts\python.exe -m pip install --upgrade build twine
.\.venv\Scripts\python.exe -m build --wheel    # wheel only on Windows;
                                               # CI builds sdist on Linux
.\.venv\Scripts\python.exe -m twine check dist\*

# Try installing into a fresh venv
py -3.12 -m venv C:\tmp\mslisa-local
$wheel = (Get-Item dist\mslisa-*.whl).FullName
& C:\tmp\mslisa-local\Scripts\python.exe -m pip install "$wheel[azure]"
& C:\tmp\mslisa-local\Scripts\lisa.exe --help
```

---

## Known limitations

- **sdist build fails on Windows** because `setuptools_scm` includes every git-
  tracked file (including deeply nested logs under `lisa/ai/data/...`) and the
  resulting paths exceed Windows' 260-character limit. CI builds on Linux are
  unaffected. The wheel is what users actually install.
- **`MANIFEST.in` `prune` rules don't apply** to files already tracked by git
  when `setuptools_scm` is the file finder. To shrink the sdist, move
  `lisa/ai/data/` out of git (git-lfs or a sibling repo).
- **Optional extras** (`baremetal`, `aws`, `ai`, etc.) are *not* installed by
  `pip install mslisa`. Users opt in with `pip install "mslisa[azure,ai,…]"`.
