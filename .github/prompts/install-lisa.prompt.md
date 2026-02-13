# Install LISA

You are helping the user install Microsoft LISA (Linux Integration Services Automation).
Detect the user's operating system and follow the appropriate installation method below.

## Windows Installation

Run the PowerShell quick install script:

```powershell
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

### Remote installation (no local repo)

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/microsoft/lisa/main/quick-install.ps1" -OutFile "$env:TEMP\quick-install.ps1"; & "$env:TEMP\quick-install.ps1"
```

---

## Linux Installation

Run the bash quick install script:

```bash
curl -fsSL https://raw.githubusercontent.com/microsoft/lisa/main/quick-install.sh | bash
```

Or download and run with options:

```bash
curl -fsSL https://raw.githubusercontent.com/microsoft/lisa/main/quick-install.sh -o quick-install.sh
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

## Docker Installation

```bash
docker run --rm -i mcr.microsoft.com/lisa/runtime:latest lisa -r lisa/examples/runbook/hello_world.yml
```

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

## Troubleshooting

### "lisa" command not found
- **Windows**: Restart PowerShell to refresh PATH
- **Linux**: Ensure `~/.local/bin` is in PATH: `export PATH="$HOME/.local/bin:$PATH"`

### Python version too old
- Re-run the install script with `--python-version 3.12` (Linux) or `-PythonVersion "3.12"` (Windows)

### Permission errors
- **Windows**: Run PowerShell as Administrator
- **Linux**: Use `--user` flag with pip, or use `--use-venv true`

### Build errors during installation
- Install development packages:
  - Ubuntu/Debian: `sudo apt-get install -y python3-dev build-essential libssl-dev libffi-dev`
  - RHEL/CentOS: `sudo dnf install -y python3-devel gcc openssl-devel libffi-devel`

For detailed documentation, see `INSTALL.md` in the repository root.
