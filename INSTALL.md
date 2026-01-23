# LISA Installation Guide

This guide provides installation instructions for Microsoft LISA on both Windows and Linux platforms.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Windows Installation](#windows-installation)
- [Linux Installation](#linux-installation)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Common Requirements
- **Python**: 3.11 or higher (3.8+ minimum)
- **Git**: Latest stable version
- **Internet connection**: For downloading dependencies

### Windows-Specific Requirements
- **Visual C++ Redistributable**: [Download here](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- **PowerShell**: 5.1 or higher (included in Windows 10/11)

### Linux-Specific Requirements
- **gcc/build-essential**: For compiling Python extensions
- **libssl-dev**: For SSL support
- **python3-dev**: Python development headers

---

## Windows Installation

### Option 1: Quick Install (Recommended)

The quick install script automatically downloads and installs everything you need.

1. **Open PowerShell as Administrator**

2. **Download and run the installation script directly:**
   ```powershell
   # Download and run the script in one command
   Invoke-WebRequest -Uri "https://raw.githubusercontent.com/microsoft/lisa/main/quick-install.ps1" -OutFile "$env:TEMP\quick-install.ps1"; & "$env:TEMP\quick-install.ps1"
   ```

   Or download the script manually first:
   ```powershell
   # Download the script
   Invoke-WebRequest -Uri "https://raw.githubusercontent.com/microsoft/lisa/main/quick-install.ps1" -OutFile "quick-install.ps1"
   
   # Run the installation script
   .\quick-install.ps1
   ```

3. **Optional parameters:**
   ```powershell
   # Specify Python version (default: 3.12)
   .\quick-install.ps1 -PythonVersion "3.11"

   # Skip Python version check (use existing Python)
   .\quick-install.ps1 -SkipPython

   # Specify custom installation path (default: $env:USERPROFILE\lisa)
   .\quick-install.ps1 -InstallPath "C:\MyTools\lisa"

   # Install from a different branch
   .\quick-install.ps1 -Branch "develop"
   ```

### Option 2: Manual Installation

1. **Install Python**
   - Download Python 3.11+ from [python.org](https://www.python.org/downloads/)
   - During installation, check "Add Python to PATH"
   - Verify: `python --version`

2. **Install Git**
   - Download from [git-scm.com](https://git-scm.com/download/win)
   - Use default settings during installation
   - Verify: `git --version`

3. **Install Visual C++ Redistributable**
   - Download and install from [Microsoft](https://aka.ms/vs/17/release/vc_redist.x64.exe)

4. **Install Python dependencies**
   ```powershell
   python -m pip install --upgrade pip
   pip install --user --upgrade nox toml wheel
   ```

5. **Clone LISA repository**
   ```powershell
   git clone https://github.com/microsoft/lisa.git
   cd lisa
   ```

6. **Install LISA with Azure extensions**
   ```powershell
   pip install -e .[azure]
   ```

7. **Add Python Scripts to PATH** (if not already)
   ```powershell
   $scriptsPath = python -c "import site; import os; print(os.path.join(site.USER_BASE, 'Scripts'))"
   [Environment]::SetEnvironmentVariable('PATH', $env:PATH + ";$scriptsPath", 'User')
   ```

---

## Linux Installation

### Option 1: Quick Install (Recommended)

The quick install script automatically downloads and installs everything you need.

```bash
# Download and run the script in one command
curl -fsSL https://raw.githubusercontent.com/microsoft/lisa/main/quick-install.sh | bash
```

Or download the script manually first:
```bash
# Download the script
curl -fsSL https://raw.githubusercontent.com/microsoft/lisa/main/quick-install.sh -o quick-install.sh

# Make it executable and run
chmod +x quick-install.sh
./quick-install.sh
```

**Optional parameters:**
```bash
# Specify Python version (default: 3.12)
./quick-install.sh --python-version 3.11

# Specify custom installation path (default: ~/lisa)
./quick-install.sh --install-path /opt/lisa

# Install from a different branch
./quick-install.sh --branch develop

# Use virtual environment (recommended for isolation)
./quick-install.sh --use-venv

# Show all available options
./quick-install.sh --help
```

### Option 2: Manual Installation

#### Ubuntu/Debian

1. **Update package list and install prerequisites**
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3 python3-pip python3-dev git build-essential libssl-dev
   ```

2. **Verify Python version** (should be 3.8+)
   ```bash
   python3 --version
   ```
   
   If Python is too old, install Python 3.11:
   ```bash
   sudo apt-get install -y software-properties-common
   sudo add-apt-repository ppa:deadsnakes/ppa
   sudo apt-get update
   sudo apt-get install -y python3.11 python3.11-dev python3.11-venv
   sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
   ```

3. **Install Python dependencies**
   ```bash
   python3 -m pip install --upgrade pip
   pip3 install --user --upgrade nox toml wheel
   ```

4. **Clone LISA repository**
   ```bash
   git clone https://github.com/microsoft/lisa.git
   cd lisa
   ```

5. **Install LISA with Azure extensions**
   ```bash
   pip3 install -e .[azure]
   ```

6. **Add local bin to PATH** (if not already)
   ```bash
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
   source ~/.bashrc
   ```

### RHEL/CentOS/Fedora

1. **Install prerequisites**
   ```bash
   # RHEL/CentOS 8+
   sudo dnf install -y python3 python3-pip python3-devel git gcc openssl-devel
   
   # RHEL/CentOS 7
   sudo yum install -y python3 python3-pip python3-devel git gcc openssl-devel
   ```

2. **Follow steps 2-6 from Ubuntu/Debian** section above

### SUSE/openSUSE

1. **Install prerequisites**
   ```bash
   sudo zypper install -y python3 python3-pip python3-devel git gcc libopenssl-devel
   ```

2. **Follow steps 2-6 from Ubuntu/Debian** section above

---

## Verification

After installation, verify LISA is working correctly:

### Check LISA version
```bash
# Windows PowerShell or Linux Terminal
lisa --version
```

### Run a simple test
```bash
lisa --help
```

### Test Azure connectivity (if using Azure extensions)
```bash
lisa -l azure
```

Expected output should show available Azure platforms and no errors.

---

## Troubleshooting

### Windows Issues

**Problem: "lisa" command not found**
- Solution: Restart PowerShell/Command Prompt to refresh PATH
- Or manually add Python Scripts directory to PATH:
  ```powershell
  $env:PATH += ";$env:USERPROFILE\AppData\Roaming\Python\Python311\Scripts"
  ```

**Problem: SSL/TLS errors during pip install**
- Solution: Upgrade pip and setuptools:
  ```powershell
  python -m pip install --upgrade pip setuptools certifi
  ```

**Problem: Permission denied errors**
- Solution: Run PowerShell as Administrator or use `--user` flag:
  ```powershell
  pip install --user -e .[azure]
  ```

### Linux Issues

**Problem: "lisa" command not found**
- Solution: Ensure `~/.local/bin` is in PATH:
  ```bash
  export PATH="$HOME/.local/bin:$PATH"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  ```

**Problem: Python version too old**
- Solution: Install newer Python from source or use distribution-specific PPA/repository

**Problem: Build errors during installation**
- Solution: Install development packages:
  ```bash
  # Ubuntu/Debian
  sudo apt-get install -y python3-dev build-essential libssl-dev libffi-dev
  
  # RHEL/CentOS
  sudo dnf install -y python3-devel gcc openssl-devel libffi-devel
  ```

**Problem: Permission errors**
- Solution: Use `--user` flag with pip:
  ```bash
  pip3 install --user -e .[azure]
  ```

### Common Issues (Both Platforms)

**Problem: Out of date dependencies**
- Solution: Upgrade all packages:
  ```bash
  # Windows
  pip install --upgrade -e .[azure]
  
  # Linux
  pip3 install --upgrade -e .[azure]
  ```

**Problem: Conflicting Python installations**
- Solution: Use Python virtual environment:
  ```bash
  # Create virtual environment
  python3 -m venv lisa-env
  
  # Activate it
  # Windows:
  lisa-env\Scripts\activate
  # Linux:
  source lisa-env/bin/activate
  
  # Install LISA
  pip install -e .[azure]
  ```

---

## Next Steps

After successful installation:

1. **Review Documentation**: Check the [official LISA documentation](https://github.com/microsoft/lisa)
2. **Create a Runbook**: Configure your test environment in a YAML runbook file
3. **Run Your First Test**:
   ```bash
   lisa -r your-runbook.yml
   ```

For more information and examples, visit the [LISA GitHub repository](https://github.com/microsoft/lisa).
