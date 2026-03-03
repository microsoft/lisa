#!/bin/bash
# Quick Install Script for Microsoft LISA on Linux
# This script installs upstream LISA from https://github.com/microsoft/lisa

set -e

# Default parameters
SKIP_PYTHON=false
PYTHON_VERSION="3.12"
INSTALL_PATH="$HOME/lisa"
BRANCH="main"
USE_VENV="auto"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-python)
            SKIP_PYTHON=true
            shift
            ;;
        --python-version)
            PYTHON_VERSION="$2"
            shift 2
            ;;
        --install-path)
            INSTALL_PATH="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --use-venv)
            USE_VENV="$2"
            if [[ "$USE_VENV" != "true" && "$USE_VENV" != "false" && "$USE_VENV" != "auto" ]]; then
                echo "Error: --use-venv must be 'true', 'false', or 'auto'"
                exit 1
            fi
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --skip-python         Skip Python installation check"
            echo "  --python-version VER  Python version to install (default: 3.12)"
            echo "  --install-path PATH   Installation directory (default: ~/lisa)"
            echo "  --branch BRANCH       Git branch to clone (default: main)"
            echo "  --use-venv MODE       Use virtual environment: true, false, or auto (default: auto)"
            echo "                        auto: use venv on Ubuntu 24.04+ to avoid PEP 668"
            echo "  --help               Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage information"
            exit 1
            ;;
    esac
done

echo "===== Microsoft LISA Quick Installation Script ====="
echo "Installing from: https://github.com/microsoft/lisa"

# Detect Linux distribution
if [ -f /etc/os-release ]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    OS=$ID
    OS_VERSION=$VERSION_ID
else
    echo "[ERROR] Cannot detect Linux distribution"
    exit 1
fi

echo "[INFO] Detected OS: $OS $OS_VERSION"

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to get Python version
get_python_version() {
    if command_exists python3; then
        python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))'
    else
        echo "0.0"
    fi
}

# Function to compare versions
version_ge() {
    [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" = "$2" ]
}

# Step 1: Check and install Python
if [ "$SKIP_PYTHON" = false ]; then
    echo "[1/4] Checking Python..."
    
    CURRENT_VERSION=$(get_python_version)
    
    # Check if we need to upgrade Python
    NEED_UPGRADE=false
    
    if command_exists python3 && version_ge "$CURRENT_VERSION" "3.8"; then
        echo "  [OK] Python is installed: $(python3 --version)"
        
        # Check if current version meets LISA requirements (3.8+)
        if ! version_ge "$CURRENT_VERSION" "3.8"; then
            echo "  [WARN] Python $CURRENT_VERSION is too old. LISA requires Python 3.8+."
            echo "  Will upgrade to Python $PYTHON_VERSION..."
            NEED_UPGRADE=true
        elif ! version_ge "$CURRENT_VERSION" "3.11"; then
            echo "  [WARN] Python 3.11+ is recommended for best compatibility. Current: $CURRENT_VERSION"
            echo "  Consider upgrading to Python 3.11 or higher"
        fi
    else
        echo "  Python 3.8+ not found. Installing Python $PYTHON_VERSION..."
        NEED_UPGRADE=true
    fi

    if [ "$NEED_UPGRADE" = true ]; then
        case $OS in
            ubuntu|debian)
                sudo apt-get update -qq
                
                # For Ubuntu 24.04+, use default python3 package
                if [ "$OS" = "ubuntu" ] && version_ge "$OS_VERSION" "24.04"; then
                    echo "  Installing python3 and essential packages..."
                    sudo apt-get install -y python3 python3-dev python3-venv
                    echo "  [OK] Python installed: $(python3 --version)"
                else
                    # For older Ubuntu versions (< 24.04), use deadsnakes PPA for Python 3.11+
                    echo "  Using apt-get to install Python $PYTHON_VERSION..."

                    NEED_PPA=false
                    if [ "$OS" = "ubuntu" ] && version_ge "$PYTHON_VERSION" "3.11"; then
                        NEED_PPA=true
                    fi

                    if [ "$NEED_PPA" = true ]; then
                        echo "  Adding deadsnakes PPA for Python $PYTHON_VERSION..."
                        sudo apt-get install -y software-properties-common
                        sudo add-apt-repository -y ppa:deadsnakes/ppa
                        sudo apt-get update -qq
                    fi

                    # Install specific Python version
                    PYTHON_PACKAGE="python${PYTHON_VERSION}"
                    echo "  Installing ${PYTHON_PACKAGE}..."

                    # Install base Python (required) - use exact package name to avoid regex matching
                    sudo apt install -y --no-install-recommends "${PYTHON_PACKAGE}"

                    # Install optional packages (don't fail if unavailable)
                    set +e  # Temporarily disable exit on error
                    sudo apt-get install -y "${PYTHON_PACKAGE}-dev" 2>/dev/null || echo "  [INFO] ${PYTHON_PACKAGE}-dev not available, skipping"
                    sudo apt-get install -y "${PYTHON_PACKAGE}-venv" 2>/dev/null || echo "  [INFO] ${PYTHON_PACKAGE}-venv not available, skipping"
                    if ! version_ge "$PYTHON_VERSION" "3.12"; then
                        sudo apt-get install -y "${PYTHON_PACKAGE}-distutils" 2>/dev/null || echo "  [INFO] ${PYTHON_PACKAGE}-distutils not available, skipping"
                    fi
                    set -e  # Re-enable exit on error

                    # Refresh command hash to detect newly installed python
                    hash -r 2>/dev/null || true

                    # Find where python was actually installed (search common bin directories first for performance)
                    PYTHON_BIN=$(which "python${PYTHON_VERSION}" 2>/dev/null || \
                        find /usr/bin /usr/local/bin -name "python${PYTHON_VERSION}" -type f -executable 2>/dev/null | head -1)

                    if [ -z "$PYTHON_BIN" ]; then
                        echo "  [ERROR] Python ${PYTHON_VERSION} installation failed - binary not found"
                        echo "  [INFO] Searching for installed Python versions..."
                        find /usr/bin /usr/local/bin -name "python3.*" -type f -executable 2>/dev/null | head -10
                        exit 1
                    fi

                    echo "  [INFO] Found Python ${PYTHON_VERSION} at: $PYTHON_BIN"

                    # Update alternatives to make new Python the default
                    if [ -x "$PYTHON_BIN" ]; then
                        # Set higher priority (100) to make it the default
                        sudo update-alternatives --install /usr/bin/python3 python3 "$PYTHON_BIN" 100
                        sudo update-alternatives --set python3 "$PYTHON_BIN"

                        # Refresh shell command cache
                        hash -r 2>/dev/null || true

                        # Verify the switch worked
                        ACTUAL_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
                        if [ "$ACTUAL_VERSION" = "$PYTHON_VERSION" ]; then
                            echo "  [OK] Python ${PYTHON_VERSION} installed and set as default ($(python3 --version))"
                        else
                            echo "  [WARN] Python switch incomplete. Current: $ACTUAL_VERSION, Expected: $PYTHON_VERSION"
                            echo "  [INFO] You can use python${PYTHON_VERSION} directly: $PYTHON_BIN"
                        fi
                    else
                        echo "  [ERROR] Python binary not executable: $PYTHON_BIN"
                        exit 1
                    fi
                fi
                ;;
            rhel|centos|fedora|rocky|almalinux)
                echo "  Using yum/dnf to install Python..."
                if command_exists dnf; then
                    sudo dnf install -y python3 python3-pip python3-devel
                else
                    sudo yum install -y python3 python3-pip python3-devel
                fi
                ;;
            sles|opensuse*)
                echo "  Using zypper to install Python..."
                sudo zypper install -y python3 python3-pip python3-devel
                ;;
            *)
                echo "  [ERROR] Unsupported distribution: $OS"
                echo "  Please install Python 3.8+ manually"
                exit 1
                ;;
        esac

        # Verify installation
        if command_exists python3; then
            CURRENT_VERSION=$(get_python_version)
            echo "  [OK] Python installed: $(python3 --version)"
        else
            echo "  [ERROR] Python installation failed"
            exit 1
        fi
    fi
else
    echo "[1/4] Skipping Python check"
fi

# Step 2: Install Python dependencies
echo "[2/4] Installing system dependencies..."

# Install system dependencies based on distribution
case $OS in
    ubuntu|debian)
        echo "  Installing Ubuntu/Debian dependencies..."
        sudo apt-get update -qq
        sudo apt install -y git gcc libgirepository1.0-dev libcairo2-dev qemu-utils libvirt-dev python3-pip python3-venv 2>/dev/null || \
        sudo apt install -y git gcc python3-pip python3-venv 2>/dev/null || \
        echo "  [WARN] Some optional packages may not be available"
        ;;
    rhel|centos|fedora|rocky|almalinux)
        echo "  Installing RHEL/Fedora dependencies..."
        if command_exists dnf; then
            # Fedora 41+ or RHEL 9+
            sudo dnf install -y git gcc gobject-introspection-devel cairo-devel qemu-img libvirt-devel python3-pip python3-virtualenv 2>/dev/null || \
            sudo dnf install -y git gcc python3-pip python3-virtualenv
        else
            sudo yum install -y git gcc python3-pip python3-devel
        fi
        ;;
    azurelinux|mariner)
        echo "  Installing Azure Linux dependencies..."
        sudo tdnf install -y git gcc gobject-introspection-devel cairo-gobject cairo-devel pkg-config libvirt-devel python3-devel python3-pip python3-virtualenv build-essential cairo-gobject-devel curl wget tar azure-cli ca-certificates 2>/dev/null || \
        sudo tdnf install -y git gcc python3-pip python3-devel
        ;;
    sles|opensuse*)
        echo "  Installing SUSE dependencies..."
        sudo zypper install -y git gcc python3-pip python3-devel
        ;;
    *)
        echo "  [WARN] Unknown distribution, installing basic dependencies..."
        echo "  Please refer to: https://mslisa.readthedocs.io/en/main/installation_linux.html"
        ;;
esac

echo "[3/4] Installing pip and Python packages..."

# Ensure pip is available
if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "  Installing pip..."

    # Try package manager first
    case $OS in
        ubuntu|debian)
            # For Ubuntu 24.04+, use get-pip.py directly (PEP 668 externally-managed-environment)
            if [ "$OS" = "ubuntu" ] && version_ge "$OS_VERSION" "24.04"; then
                echo "  Ubuntu 24.04+ detected, installing pip via get-pip.py..."
                CURRENT_VERSION=$(get_python_version)
                GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"

                curl -sS "$GET_PIP_URL" -o /tmp/get-pip.py
                # Use --break-system-packages to bypass PEP 668 restriction
                python3 /tmp/get-pip.py --break-system-packages 2>/dev/null || python3 /tmp/get-pip.py
                rm -f /tmp/get-pip.py
                echo "  [OK] pip installed via get-pip.py"
            else
                # Already installed via apt install python3-pip above
                if ! python3 -m pip --version >/dev/null 2>&1; then
                    # Fallback if not installed
                    echo "  python3-pip not detected, trying alternative methods..."
                    if ! python3 -m ensurepip --default-pip 2>/dev/null; then
                        CURRENT_VERSION=$(get_python_version)
                        if version_ge "$CURRENT_VERSION" "3.9"; then
                            GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"
                        else
                            GET_PIP_URL="https://bootstrap.pypa.io/pip/3.8/get-pip.py"
                        fi

                        echo "  Downloading get-pip.py for Python $CURRENT_VERSION..."
                        curl -sS "$GET_PIP_URL" -o /tmp/get-pip.py
                        python3 /tmp/get-pip.py
                        rm -f /tmp/get-pip.py
                    fi
                fi
            fi
            ;;
        *)
            # For other distros, pip should be installed by package manager above
            if ! python3 -m pip --version >/dev/null 2>&1; then
                echo "  [WARN] pip not available, trying to install..."
                python3 -m ensurepip --default-pip 2>/dev/null || true
            fi
            ;;
    esac

    # Verify pip installation
    if ! python3 -m pip --version >/dev/null 2>&1; then
        echo "  [ERROR] Failed to install pip"
        exit 1
    fi
fi

# Upgrade pip (skip for Ubuntu 24.04+ as it will be done in venv, skip for Azure Linux as pip is managed by rpm)
if [ "$OS" = "ubuntu" ] && version_ge "$OS_VERSION" "24.04"; then
    echo "  [INFO] Skipping pip upgrade (will upgrade in virtual environment)"
elif [ "$OS" = "azurelinux" ] || [ "$OS" = "mariner" ]; then
    echo "  [INFO] Skipping pip upgrade (pip is managed by system package manager on Azure Linux)"
else
    echo "  Upgrading pip..."
    python3 -m pip install --upgrade pip 2>/dev/null || echo "  [INFO] pip upgrade skipped (may be managed by system)"
fi

# Add user bin to PATH if not already there
USER_BIN="$HOME/.local/bin"
if [ -d "$USER_BIN" ] && ! echo "$PATH" | grep -q "$USER_BIN"; then
    export PATH="$USER_BIN:$PATH"
    echo "  [INFO] Added $USER_BIN to PATH for current session"

    # Add to shell rc file
    for rc_file in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc"; do
        if [ -f "$rc_file" ]; then
            if ! grep -q "$USER_BIN" "$rc_file"; then
                echo "export PATH=\"$USER_BIN:\$PATH\"" >> "$rc_file"
                echo "  [INFO] Added to $rc_file for future sessions"
            fi
            break
        fi
    done
fi

echo "  [OK] Dependencies installed"

# Step 4: Clone and install LISA
echo "[4/4] Installing LISA from GitHub..."

NEEDS_CLONE=true

if [ -d "$INSTALL_PATH" ]; then
    echo "  Directory $INSTALL_PATH already exists, removing it..."
    rm -rf "$INSTALL_PATH"
    echo "  Cloning LISA repository..."
    git clone --branch "$BRANCH" https://github.com/microsoft/lisa.git "$INSTALL_PATH" --quiet
    NEEDS_CLONE=false
fi

if [ "$NEEDS_CLONE" = true ] && [ ! -d "$INSTALL_PATH" ]; then
    echo "  Cloning LISA repository to $INSTALL_PATH..."
    git clone --branch "$BRANCH" https://github.com/microsoft/lisa.git "$INSTALL_PATH" --quiet
fi

# Verify clone was successful
if [ ! -f "$INSTALL_PATH/pyproject.toml" ]; then
    echo "  [ERROR] LISA repository clone failed or incomplete"
    echo "  Expected file not found: $INSTALL_PATH/pyproject.toml"
    exit 1
fi

echo "  Installing LISA with Azure extensions in editable mode..."
cd "$INSTALL_PATH"

# Check Python version before installing
CURRENT_VERSION=$(get_python_version)
if ! version_ge "$CURRENT_VERSION" "3.8"; then
    echo "  [ERROR] Python $CURRENT_VERSION is too old. LISA requires Python 3.8+"
    echo "  Please install Python 3.12 or higher"
    exit 1
fi

# Determine if we should use virtual environment
# USE_VENV can be: "auto", "true", or "false"
if [ "$USE_VENV" = "auto" ]; then
    # Auto-detect: use venv for Ubuntu 24.04+ to avoid PEP 668
    if [ "$OS" = "ubuntu" ] && version_ge "$OS_VERSION" "24.04"; then
        USE_VENV=true
        echo "  [INFO] Ubuntu 24.04+ detected, using virtual environment to avoid PEP 668 restrictions"
    else
        USE_VENV=false
    fi
elif [ "$USE_VENV" = "true" ]; then
    echo "  [INFO] Using virtual environment as specified by --use-venv"
else
    USE_VENV=false
    echo "  [INFO] Not using virtual environment as specified by --use-venv"
fi

# Install LISA with Azure and libvirt extensions (following official documentation)
echo "  Installing LISA and dependencies..."

if [ "$USE_VENV" = true ]; then
    # Create virtual environment
    echo "  Creating virtual environment..."
    python3 -m venv venv

    # Upgrade pip in venv
    echo "  Upgrading pip in virtual environment..."
    venv/bin/pip install --upgrade pip

    # Install LISA in venv
    if ! venv/bin/pip install --editable '.[azure,libvirt]' --config-settings editable_mode=compat; then
        echo "  [ERROR] LISA installation failed"
        echo ""
        echo "  Common causes:"
        echo "  1. Missing system dependencies"
        echo "  2. Network issues downloading packages"
        echo ""
        echo "  Recommended solutions:"
        echo "  - Install build dependencies: sudo apt install build-essential python3-dev"
        echo "  - Check error messages above for specific missing packages"
        echo "  - Visit: https://mslisa.readthedocs.io/en/main/troubleshooting.html"
        exit 1
    fi

    LISA_BIN="$INSTALL_PATH/venv/bin/lisa"
else
    # Install directly (for older Ubuntu or other distros)
    # Add extra args based on OS to handle package manager conflicts
    PIP_EXTRA_ARGS=""
    if [ "$OS" = "ubuntu" ] && version_ge "$OS_VERSION" "24.04"; then
        echo "  [WARN] Installing system-wide on Ubuntu 24.04+ (PEP 668 override)"
        PIP_EXTRA_ARGS="--break-system-packages"
    elif [ "$OS" = "azurelinux" ] || [ "$OS" = "mariner" ]; then
        echo "  [INFO] Azure Linux detected, using --ignore-installed to avoid rpm conflicts"
        PIP_EXTRA_ARGS="--ignore-installed"
    fi

    if ! python3 -m pip install --editable '.[azure,libvirt]' --config-settings editable_mode=compat $PIP_EXTRA_ARGS; then
        echo "  [ERROR] LISA installation failed"
        echo ""
        echo "  Common causes:"
        echo "  1. Python version too old (need 3.8+, have $CURRENT_VERSION)"
        echo "  2. Missing system dependencies"
        echo ""
        echo "  Recommended solutions:"
        echo "  - Install build dependencies: sudo apt install build-essential python3-dev"
        echo "  - Check error messages above for specific missing packages"
        echo "  - Visit: https://mslisa.readthedocs.io/en/main/troubleshooting.html"
        exit 1
    fi

    LISA_BIN="$HOME/.local/bin/lisa"
fi

echo "  [OK] LISA installed from $INSTALL_PATH"

# Verify installation
echo "===== Verifying Installation ====="

# For non-venv installs, try to find lisa in common locations
if [ "$USE_VENV" != true ]; then
    if [ ! -x "$LISA_BIN" ]; then
        # Try to find lisa in PATH or common locations
        LISA_FOUND=$(command -v lisa 2>/dev/null || find /usr/local/bin /usr/bin "$HOME/.local/bin" -name "lisa" -type f -executable 2>/dev/null | head -1)
        if [ -n "$LISA_FOUND" ]; then
            LISA_BIN="$LISA_FOUND"
        fi
    fi
fi

if [ -x "$LISA_BIN" ] || command -v lisa >/dev/null 2>&1; then
    if [ -x "$LISA_BIN" ]; then
        echo "[OK] LISA executable found: $LISA_BIN"
    else
        echo "[OK] LISA is available in PATH"
    fi
    echo "Verifying LISA installation..."

    if [ "$USE_VENV" = true ]; then
        "$LISA_BIN" --help > /dev/null 2>&1 && echo "[OK] LISA is working correctly" || echo "[WARN] LISA may not be configured correctly"
    else
        lisa --help > /dev/null 2>&1 && echo "[OK] LISA is working correctly" || echo "[WARN] LISA may not be configured correctly"
    fi

    echo "===== Installation Completed Successfully! ====="
    echo "LISA installed to: $INSTALL_PATH"

    if [ "$USE_VENV" = true ]; then
        echo ""
        echo "LISA is installed in a virtual environment."
        echo "To use LISA, you have three options:"
        echo ""
        echo "Option 1 - Activate the virtual environment:"
        echo "  cd $INSTALL_PATH"
        echo "  source venv/bin/activate"
        echo "  lisa"
        echo ""
        echo "Option 2 - Use the full path:"
        echo "  $INSTALL_PATH/venv/bin/lisa"
        echo ""
        echo "Option 3 - Create an alias (add to ~/.bashrc):"
        echo "  alias lisa='$INSTALL_PATH/venv/bin/lisa'"
    else
        echo "You can now run LISA with: lisa"
        if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
            echo ""
            echo "[INFO] If 'lisa' command is not found, add this to your shell config:"
            echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
    fi

    echo ""
    echo "For help, run: lisa --help"
    echo "[NOTE] Optional packages (baremetal, aws, ai) can be installed separately if needed."
    echo "To get started:"
    echo "  1. Create a runbook file"
    echo "  2. Run: lisa -r <your-runbook.yml>"

    # For venv installations, offer to activate it
    if [ "$USE_VENV" = true ]; then
        echo ""
        echo "========================================="
        echo "To activate the virtual environment now, run:"
        echo "  cd $INSTALL_PATH && source venv/bin/activate"
        echo "========================================="
    fi
else
    echo "[ERROR] LISA executable not found at: $LISA_BIN"
    echo "Installation may have failed. Please check error messages above."
    exit 1
fi
