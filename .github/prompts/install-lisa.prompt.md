# Install LISA

You are helping the user install Microsoft LISA (Linux Integration Services Automation).
Detect the user's operating system and follow the appropriate installation method below.

## Docker (Recommended, Fastest)

No local Python or dependency setup required.

```bash
docker run --rm -i mcr.microsoft.com/lisa/runtime:latest lisa -r lisa/examples/runbook/hello_world.yml
```

For running with Azure subscription, use the quick-container scripts:
- **Linux**: `quick-container.sh` — see `docs/docker_linux.rst`
- **Windows**: `quick-container.ps1` — see `docs/docker_windows.rst`

---

## Windows Installation

Run the PowerShell quick install script:

```powershell
# Download and run the script in one command
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/microsoft/lisa/main/installers/quick-install.ps1" -UseBasicParsing -OutFile "$env:TEMP\quick-install.ps1"; & "$env:TEMP\quick-install.ps1"
```

Or download the script manually first:

```powershell
# Download the script
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/microsoft/lisa/main/installers/quick-install.ps1" -UseBasicParsing -OutFile "quick-install.ps1"

# Run the installation script
.\quick-install.ps1
```

### Available Parameters

| Parameter | Default | Description |
|---|---|---|
| `-PythonVersion` | `3.12` | Python version to install |
| `-InstallPath` | `$env:USERPROFILE\lisa` | Installation directory |
| `-Branch` | `main` | Git branch to clone |
| `-SkipPython` | (switch) | Skip Python installation check |

### Examples

```powershell
# Default installation
.\quick-install.ps1

# Specify Python version
.\quick-install.ps1 -PythonVersion "3.11"

# Custom install path
.\quick-install.ps1 -InstallPath "C:\MyTools\lisa"

# Install from a specific branch
.\quick-install.ps1 -Branch "develop"

# Skip Python check (use existing Python)
.\quick-install.ps1 -SkipPython
```

### What the script does (Windows)

1. **Checks/installs Python** — uses winget or direct download from python.org
2. **Installs Python dependencies** — pip, nox, toml, wheel
3. **Checks/installs Git** — uses winget or direct download
4. **Clones and installs LISA** — clones the repo and runs `pip install --editable .[azure]`

---

## Linux Installation

Run the bash quick install script:

```bash
curl -fsSL https://raw.githubusercontent.com/microsoft/lisa/main/installers/quick-install.sh | bash
```

Or download and run with options:

```bash
curl -fsSL https://raw.githubusercontent.com/microsoft/lisa/main/installers/quick-install.sh -o quick-install.sh
chmod +x quick-install.sh
./quick-install.sh [OPTIONS]
```

### Available Parameters

| Parameter | Default | Description |
|---|---|---|
| `--python-version VER` | `3.12` | Python version to install |
| `--install-path PATH` | `~/lisa` | Installation directory |
| `--branch BRANCH` | `main` | Git branch to clone |
| `--use-venv MODE` | `auto` | Virtual environment: `true`, `false`, or `auto` |
| `--skip-python` | (flag) | Skip Python installation check |
| `--help` | | Show help message |

### Examples

```bash
# Default installation
./quick-install.sh

# Specify Python version
./quick-install.sh --python-version 3.11

# Custom install path
./quick-install.sh --install-path /opt/lisa

# Install from a specific branch
./quick-install.sh --branch develop

# Force virtual environment usage
./quick-install.sh --use-venv true

# Combine options
./quick-install.sh --python-version 3.11 --install-path /opt/lisa --use-venv true
```

### What the script does (Linux)

1. **Detects Linux distribution** — Ubuntu, Debian, RHEL, CentOS, Fedora, SUSE, Azure Linux
2. **Checks/installs Python** — uses distribution package manager (apt, dnf, zypper)
3. **Installs Python dependencies** — pip, nox, toml, wheel
4. **Checks/installs Git** — uses distribution package manager
5. **Clones and installs LISA** — clones the repo and runs `pip install --editable .[azure]`
6. **Handles PEP 668** — automatically uses venv on Ubuntu 24.04+ when needed

### Supported Linux Distributions

- Ubuntu (18.04+)
- Debian
- RHEL / CentOS / AlmaLinux / Rocky Linux
- Fedora
- SUSE / openSUSE
- Azure Linux (CBL-Mariner)

---

## WSL Bootstrap (from Windows)

Use when you want LISA to run inside WSL but you're driving everything from a
Windows PowerShell prompt. The script will install the requested distro via
`wsl --install` (if missing), then run `quick-install.sh` inside it.

```powershell
# Default: Ubuntu, main branch
.\installers\quick-install-wsl.ps1

# Custom distro / branch / install path inside WSL
.\installers\quick-install-wsl.ps1 -Distro Ubuntu-22.04 -Branch main -InstallPath '/home/$USER/lisa'

# Distro must already exist; never run wsl --install
.\installers\quick-install-wsl.ps1 -SkipWslInstall
```

### Available Parameters

| Parameter | Default | Description |
|---|---|---|
| `-Distro` | `Ubuntu` | WSL distro name (must match `wsl --list --quiet`) |
| `-Branch` | `main` | Git branch of `microsoft/lisa` to install |
| `-InstallPath` | `/home/$USER/lisa` | Install directory inside WSL (literal `$USER` expanded in WSL) |
| `-SkipWslInstall` | (switch) | Fail instead of running `wsl --install` |

### What the script does

1. Verifies `wsl.exe` is available on the host.
2. If the requested distro is not installed, runs `wsl --install -d <Distro> --no-launch` (needs Administrator) and exits so the user can create a UNIX user.
3. Downloads `installers/quick-install.sh` from the chosen branch and runs it inside WSL with `--use-venv true`.
4. After install, run LISA from PowerShell with `wsl -d <Distro> -- lisa --help`, or open a WSL shell.

### When to use it

- You don't want to maintain a Linux install yourself.
- You need the full Linux toolchain (`libvirt`, native deps) but only have a Windows machine.
- Avoid for live debugging — use the **Windows Dev** flow below for VS Code F5 debug.

---

## Windows Dev Environment (VS Code F5 debug)

Use when you want a Windows-native, editable LISA install you can step through
in VS Code without WSL. Sets up `.venv`, installs `pip install -e .[azure,libvirt]`,
and writes `.vscode/launch.json` + `.vscode/settings.json` so F5 just works.

```powershell
# Default: clone microsoft/lisa to %USERPROFILE%\lisa
.\installers\quick-install-dev.ps1

# Custom path & branch
.\installers\quick-install-dev.ps1 -InstallPath C:\code\lisa -Branch main

# Reuse existing checkout (your current LISA repo)
.\installers\quick-install-dev.ps1 -InstallPath C:\code\lisa -NoClone

# Skip libvirt extra (libvirt-python often fails to build on Windows)
.\installers\quick-install-dev.ps1 -SkipLibvirt

# Don't overwrite existing launch.json
.\installers\quick-install-dev.ps1 -SkipLaunchJson
```

### Available Parameters

| Parameter | Default | Description |
|---|---|---|
| `-InstallPath` | `$env:USERPROFILE\lisa` | LISA checkout location |
| `-Branch` | `main` | Git branch to clone |
| `-PythonVersion` | `3.12` | Python version expected on host (installed via winget if missing) |
| `-NoClone` | (switch) | Reuse existing checkout at `-InstallPath` |
| `-SkipLibvirt` | (switch) | Install only `[azure]` extra; skip `[libvirt]` |
| `-SkipLaunchJson` | (switch) | Do not write `.vscode/launch.json` / `settings.json` |

### What the script does

1. Locates Python via `py -<version>` or `python.exe`; installs `Python.Python.<version>` through winget if absent.
2. Clones (or fast-forwards) `microsoft/lisa@<branch>` into `-InstallPath`.
3. Creates `.venv`, upgrades `pip setuptools wheel`, runs `pip install --editable ".[azure,libvirt]"` (auto-falls back to `[azure]` if libvirt build fails).
4. Writes `.vscode/settings.json` pinning `python.defaultInterpreterPath` to the venv, and `.vscode/launch.json` with two `debugpy` configs:
   - `Python: lisa (module)` — runs `python -m lisa -r lisa/examples/runbook/hello_world.yml -d`.
   - `Python: Current File` — debug whatever script is open.
5. Existing `launch.json` / `settings.json` are backed up to `*.bak`.

### Verifying the dev install

```powershell
& "$env:USERPROFILE\lisa\.venv\Scripts\python.exe" -m lisa --help
```

In VS Code: open the install folder, run **Python: Select Interpreter** → pick the `.venv` (already pinned via `settings.json`), then press **F5**.

### When to use it

- Source-level debugging of LISA core / extensions on Windows.
- Iterating on tests against an Azure subscription without spinning up WSL.
- Avoid if you need libvirt/baremetal features that only build on Linux — use the **WSL Bootstrap** flow above.

---

## Prerequisites

- **Python**: 3.11+ recommended (3.8+ minimum)
- **Git**: Latest stable version
- **Internet connection**: Required for downloading dependencies
- **Windows only**: Visual C++ Redistributable ([download](https://aka.ms/vs/17/release/vc_redist.x64.exe))
- **Linux only**: gcc/build-essential, libssl-dev, python3-dev

---

## Verification

After installation, verify LISA is working:

```bash
lisa --version
lisa --help
```

---

## Capture the Install Path (so runbooks can find `microsoft.testsuites`)

`microsoft/testsuites/` is loaded dynamically by LISA. The mechanism (see
`lisa/parameter_parser/runbook.py::_fix_path_for_old_code_layout`) is:

- LISA computes `<lisa_root>` from the **running** install's
  `lisa/__init__.py` location (i.e., whatever `pip` resolved the `lisa`
  console-script to).
- A runbook's `extension:` path is rewritten to `<lisa_root>/lisa/microsoft`
  and registered as the Python package `microsoft` **only when** that path
  is already under `<lisa_root>/lisa/microsoft`.
- If the user has two LISA checkouts on disk and pip picked one but the
  runbook points at the other, the rewrite silently doesn't fire and the
  run dies with `ModuleNotFoundError: No module named 'microsoft'` even
  though the directory exists.

So the install step must guarantee — and **record** — the *single* repo
that the `lisa` command actually loads from.

When install completes, do **all four** of the following:

1. **Verify which repo the `lisa` command loads from** (this is the
   authoritative `LISA_HOME`, never trust `pwd`):

   ```bash
   # Linux / WSL
   <PYTHON> -c "import lisa, pathlib; print(pathlib.Path(lisa.__file__).parent.parent)"
   ```

   ```powershell
   # Windows
   & '<PYTHON>' -c "import lisa, pathlib; print(pathlib.Path(lisa.__file__).parent.parent)"
   ```

   If the printed path is **not** the repo you just installed, there is a
   stale install winning the resolution. Fix it before continuing:

   - `<PYTHON> -m pip uninstall -y lisa` until `pip show lisa` reports nothing,
     then re-run `pip install -e .[azure]` from the desired repo, OR
   - inside the desired repo, run `<PYTHON> -m pip install -e . --force-reinstall`,
     OR
   - simply delete the unused checkout from disk.

2. **Print the absolute install path** at the end, on its own line:

   ```text
   LISA_HOME=<path printed by step 1, the running LISA's repo root>
   PYTHON=<absolute path to the python interpreter that has lisa installed>
   ```

   `PYTHON` matters whenever a venv is involved (`quick-install-dev.ps1`
   always creates one at `<install_path>\.venv`; `quick-install.sh` does
   when invoked with `--use-venv true`). Without it, opening a fresh shell
   that hasn't activated the venv either fails with `lisa: command not
   found` or silently picks up a system Python that has no LISA.

   Resolve `PYTHON` like this:
   - Windows venv: `<install_path>\.venv\Scripts\python.exe`
   - Linux/WSL venv: `<install_path>/.venv/bin/python`
   - No venv (system / `pipx` / `--user` install): record `PYTHON=python`
     so downstream tools know no activation is required.

3. **Set the `LISA_HOME` environment variable** for the current shell. If a
   venv was created, also tell the user how to activate it (or invoke the
   venv python directly without activation):

   ```powershell
   # Windows (PowerShell)
   $env:LISA_HOME = '<absolute path>'
   [Environment]::SetEnvironmentVariable('LISA_HOME', '<absolute path>', 'User')

   # If a venv exists, activate it in every new shell, OR call the venv python directly:
   & '<install_path>\.venv\Scripts\Activate.ps1'
   # — or —
   & '<install_path>\.venv\Scripts\python.exe' -m lisa --help
   ```

   ```bash
   # Linux / macOS / WSL
   export LISA_HOME='<absolute path>'
   echo 'export LISA_HOME="<absolute path>"' >> ~/.bashrc

   # If a venv exists:
   source '<install_path>/.venv/bin/activate'
   # — or —
   '<install_path>/.venv/bin/python' -m lisa --help
   ```

   Do not bake `Activate.ps1` into `$PROFILE` automatically — mention it as
   an option, let the user opt in.

4. **Record it in session memory** (so other prompts in the same workspace
   can read it without re-asking):

   - Path: `/memories/session/lisa-install.md`
   - Content:

     ```text
     LISA_HOME=<absolute path verified by step 1>
     PYTHON=<absolute path to venv python, or literally "python" if no venv>
     VENV=<absolute path to the venv root, or empty if no venv>
     ```

   The `lisa_runbook_generator` prompt reads this file and trusts step 1's
   path as authoritative — if you skip step 1 and write `pwd` here, it WILL
   bite you the moment a runbook needs microsoft testsuites.

The `microsoft/testsuites/` directory then lives at
`$LISA_HOME/lisa/microsoft/testsuites` (note the doubled `lisa/lisa/` —
the outer `lisa/` is the repo, the inner `lisa/` is the Python package).

---

## Troubleshooting

### "lisa" command not found
- **Windows**: Restart PowerShell to refresh PATH
- **Linux**: Ensure `~/.local/bin` is in PATH: `export PATH="$HOME/.local/bin:$PATH"`
- **venv install (any OS)**: the `lisa` console-script only exists inside the venv.
  Either activate it (`.venv\Scripts\Activate.ps1` / `source .venv/bin/activate`)
  or call it via the venv python without activation:
  `<install_path>/.venv/bin/python -m lisa --help` (Linux) /
  `<install_path>\.venv\Scripts\python.exe -m lisa --help` (Windows).
  After activation, `(.venv)` should appear in the prompt and `where.exe lisa`
  / `which lisa` should resolve into the venv directory.

### Wrong Python is picked up (system Python instead of venv)
Symptom: `python -c "import lisa; print(lisa.__file__)"` errors out, or points
to a different LISA install than expected, even though install succeeded.
Fix: confirm the active interpreter with `python -c "import sys; print(sys.executable)"`.
It must match the `PYTHON` line recorded in `/memories/session/lisa-install.md`.
If not, activate the venv first, or invoke the venv python explicitly
(`<venv>/bin/python` / `<venv>\Scripts\python.exe`).

### Python version too old
- Re-run the install script with `--python-version 3.12` (Linux) or `-PythonVersion "3.12"` (Windows)

### Permission errors
- **Windows**: Run PowerShell as Administrator
- **Linux**: Use `--user` flag with pip, or use `--use-venv true`

### Build errors during installation
- Install development packages:
  - Ubuntu/Debian: `sudo apt-get install -y python3-dev build-essential libssl-dev libffi-dev`
  - RHEL/CentOS: `sudo dnf install -y python3-devel gcc openssl-devel libffi-devel`

### `ModuleNotFoundError: No module named 'microsoft'` when running a runbook

Symptom: `lisa -r my_runbook.yml` logs
`loading Python extensions from <some path>` then fails with
`ModuleNotFoundError: No module named 'microsoft'`.

LISA found the directory — the failure is in the auto-rename step. The path
you gave to `extension:` must be under the **running LISA's**
`<lisa_root>/lisa/microsoft`, otherwise the loader keeps a generic name
like `lisa_ext_0` and absolute imports such as
`from microsoft.testsuites.xfstests.xfstests import ...` cannot resolve.

Fix in order of preference:
1. Re-run the **Capture the Install Path** verification step above to
   discover the running LISA's actual root
   (`<PYTHON> -c "import lisa, pathlib; print(pathlib.Path(lisa.__file__).parent.parent)"`).
2. If the printed path is not the repo you intended, you have **two LISA
   checkouts** — pip resolved the wrong one. Either `pip uninstall lisa`
   in the unused checkout, or `pip install -e . --force-reinstall` from
   the desired repo.
3. In the runbook, drop `extension:` and use

   ```yaml
   import_builtin_tests: true
   ```

   instead. LISA then loads `<running_lisa_root>/lisa/microsoft` itself —
   the path can never disagree with the install.
4. Only if you actually need a custom (non-microsoft) extension, keep
   `extension:` and make sure each entry is an absolute path under the
   *running* LISA root, or a path relative to the runbook file that
   resolves there.

### VS Code F5 hangs / debugpy traceback in `importlib.metadata`
Symptom: hitting F5 launches `C:\Program Files\Python312\python.exe` (system Python), then debugpy stalls inside `describe_environment` reading broken package METADATA.
Cause: newer `ms-python` versions ignore `launch.json`'s `"python"` field and use the workspace interpreter, which defaults to system Python (no LISA installed there).
Fix:
1. Ensure `.vscode/settings.json` contains `"python.defaultInterpreterPath": ".../.venv/Scripts/python.exe"` (the dev installer writes this automatically).
2. `Ctrl+Shift+P` → **Python: Select Interpreter** → pick the `.venv`.
3. `Ctrl+Shift+P` → **Developer: Reload Window**, then F5 again.
4. Status bar (bottom-right) must show `('.venv': venv)` before launching.

For detailed documentation, see `installers/INSTALL.md` in the repository.
