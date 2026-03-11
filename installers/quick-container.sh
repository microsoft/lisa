#!/bin/bash
# Quick Container Script for LISA
# This script helps you quickly run LISA in a Docker container on Linux

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
LISA_IMAGE="mcr.microsoft.com/lisa/runtime:latest"
RUNBOOK=""
INTERACTIVE=false
MOUNT_PATH=""
CONTAINER_NAME="lisa-runner"
REMOVE_CONTAINER=true
EXTRA_ARGS=""
SHOW_HELP=false
LISA_VARIABLES=()
SUBSCRIPTION_ID=""
AUTH_TYPE=""
ACCESS_TOKEN=""
INSTALL_DOCKER=false
INSTALL_AZCLI=false
PULL_IMAGE=false
LOG_PATH="./lisa-logs"

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to show help
show_help() {
    cat << EOF
Quick Container Script for LISA
Usage: bash quick-container.sh [OPTIONS]

OPTIONS:
    -r, --runbook PATH          Path to runbook file or container internal path (required unless -i is used)
                                - External file: ./my-runbook.yml (will be mounted)
                                - Internal path: lisa/microsoft/runbook/azure.yml (no mount needed)
    -i, --interactive           Start an interactive shell in the container
    -v, --variable KEY:VALUE    LISA variable (can be used multiple times)
                                Example: -v subscription_id:xxx -v location:westus2
    -m, --mount PATH            Mount a local directory into the container at /workspace
    -l, --log-path PATH         Local directory to save LISA logs (default: ./lisa-logs)
                                Container logs at /app/lisa/runtime will be saved here
    -n, --name NAME             Container name (default: lisa-runner)
    -k, --keep                  Keep container after exit (don't auto-remove)
    --subscription-id ID        Azure subscription ID (shortcut for -v subscription_id:xxx)
    --token TOKEN               Azure access token (shortcut for token auth)
    --image IMAGE               Docker image to use (default: mcr.microsoft.com/lisa/runtime:latest)
    --pull                      Force pull latest image (default: use local image if available)
    --extra-args ARGS           Extra arguments to pass to docker run
    --install-docker            Install Docker if not present
    --install-azcli             Install Azure CLI if not present
    -h, --help                  Show this help message

EXAMPLES:
    # Run with external runbook file
    bash quick-container.sh -r ./runbook.yml

    # Run with container internal runbook
    bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \\
        -v subscription_id:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

    # Run with Azure token authentication (recommended)
    export LISA_azure_arm_access_token=\$(az account get-access-token --query accessToken -o tsv)
    bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \\
        --subscription-id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \\
        --token "\$LISA_azure_arm_access_token"

    # Run with LISA variables
    bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \\
        -v subscription_id:xxx \\
        -v location:westus2 \\
        -v vm_size:Standard_DS2_v2

    # Mount a local directory and run
    bash quick-container.sh -r ./runbook.yml -m \$(pwd)

    # Specify custom log directory
    bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \
        --log-path ./my-test-logs

    # Start an interactive shell in the container
    bash quick-container.sh -i

    # Run with custom container name and keep it after exit
    bash quick-container.sh -r ./runbook.yml -n my-lisa-test -k

AUTHENTICATION:
    Token-based authentication (recommended):
    
    export LISA_azure_arm_access_token=\$(az account get-access-token --query accessToken -o tsv)
    bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \\
        --subscription-id xxx --token "\$LISA_azure_arm_access_token"

    Or use LISA variables directly:
    
    bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \\
        -v subscription_id:xxx \\
        -v "auth_type:token" \\
        -v "azure_arm_access_token:\$LISA_azure_arm_access_token"

    Service principal authentication:
    
    bash quick-container.sh -r lisa/microsoft/runbook/azure.yml \\
        --extra-args "-e LISA_azure_client_id=xxx -e LISA_azure_client_secret=xxx -e LISA_azure_tenant_id=xxx"

PREREQUISITES:
    - Docker must be installed and running
    - User must have permission to run Docker (add user to docker group or use sudo)

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -r|--runbook)
            RUNBOOK="$2"
            shift 2
            ;;
        -i|--interactive)
            INTERACTIVE=true
            shift
            ;;
        -v|--variable)
            LISA_VARIABLES+=("$2")
            shift 2
            ;;
        -m|--mount)
            MOUNT_PATH="$2"
            shift 2
            ;;
        -l|--log-path)
            LOG_PATH="$2"
            shift 2
            ;;
        -n|--name)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        -k|--keep)
            REMOVE_CONTAINER=false
            shift
            ;;
        --subscription-id)
            SUBSCRIPTION_ID="$2"
            shift 2
            ;;
        --token)
            ACCESS_TOKEN="$2"
            AUTH_TYPE="token"
            shift 2
            ;;
        --image)
            LISA_IMAGE="$2"
            shift 2
            ;;
        --pull)
            PULL_IMAGE=true
            shift
            ;;
        --extra-args)
            EXTRA_ARGS="$2"
            shift 2
            ;;
        --install-docker)
            INSTALL_DOCKER=true
            shift
            ;;
        --install-azcli)
            INSTALL_AZCLI=true
            shift
            ;;
        -h|--help)
            SHOW_HELP=true
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Show help if requested
if [ "$SHOW_HELP" = true ]; then
    show_help
    exit 0
fi

# Validate requirements
if [ "$INTERACTIVE" = false ] && [ -z "$RUNBOOK" ]; then
    print_error "Either --runbook or --interactive must be specified"
    echo ""
    show_help
    exit 1
fi

# Add shortcut authentication to LISA variables
if [ -n "$SUBSCRIPTION_ID" ]; then
    LISA_VARIABLES+=("subscription_id:$SUBSCRIPTION_ID")
fi
if [ -n "$AUTH_TYPE" ]; then
    LISA_VARIABLES+=("auth_type:$AUTH_TYPE")
fi
if [ -n "$ACCESS_TOKEN" ]; then
    LISA_VARIABLES+=("azure_arm_access_token:$ACCESS_TOKEN")
fi

# Function to install Docker
install_docker() {
    print_info "Installing Docker..."
    
    # Detect OS
    if [ -f /etc/os-release ]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        OS=$ID
    else
        print_error "Cannot detect OS. Please install Docker manually."
        exit 1
    fi
    
    case $OS in
        ubuntu|debian)
            print_info "Installing Docker on Ubuntu/Debian..."
            sudo apt update
            sudo apt install -y docker.io
            ;;
        azurelinux|mariner)
            print_info "Installing Docker on Azure Linux..."
            sudo tdnf update -y
            sudo tdnf install -y moby-engine moby-cli
            ;;
        centos|rhel|fedora)
            print_info "Installing Docker on RHEL/CentOS/Fedora..."
            sudo yum install -y docker
            ;;
        *)
            print_error "Unsupported OS: $OS. Please install Docker manually."
            exit 1
            ;;
    esac
    
    # Start Docker service
    print_info "Starting Docker service..."
    sudo systemctl start docker
    sudo systemctl enable docker
    
    # Add current user to docker group
    print_info "Adding current user to docker group..."
    sudo usermod -aG docker "$USER"
    
    print_info "Docker installed successfully!"
    print_warning "You may need to log out and log back in for group changes to take effect."
    print_info "Or run: newgrp docker"
}

# Function to install Azure CLI
install_azcli() {
    print_info "Installing Azure CLI..."
    
    # Detect OS
    if [ -f /etc/os-release ]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        OS=$ID
    else
        print_error "Cannot detect OS. Please install Azure CLI manually."
        exit 1
    fi
    
    case $OS in
        ubuntu|debian)
            print_info "Installing Azure CLI on Ubuntu/Debian..."
            sudo apt-get update
            sudo apt-get install -y ca-certificates curl apt-transport-https lsb-release gnupg
            
            # Download and install Microsoft signing key
            sudo mkdir -p /etc/apt/keyrings
            curl -sLS https://packages.microsoft.com/keys/microsoft.asc | \
                gpg --dearmor | \
                sudo tee /etc/apt/keyrings/microsoft.gpg > /dev/null
            sudo chmod go+r /etc/apt/keyrings/microsoft.gpg
            
            # Add Azure CLI repository
            AZ_DIST=$(lsb_release -cs)
            echo "deb [arch=\`dpkg --print-architecture\` signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ $AZ_DIST main" | \
                sudo tee /etc/apt/sources.list.d/azure-cli.list
            
            # Install Azure CLI
            sudo apt-get update
            sudo apt-get install -y azure-cli
            ;;
        azurelinux|mariner)
            print_info "Installing Azure CLI on Azure Linux..."
            sudo tdnf install -y azure-cli
            ;;
        centos|rhel|fedora)
            print_info "Installing Azure CLI on RHEL/CentOS/Fedora..."
            sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
            
            # Add repository
            echo -e "[azure-cli]
name=Azure CLI
baseurl=https://packages.microsoft.com/yumrepos/azure-cli
enabled=1
gpgcheck=1
gpgkey=https://packages.microsoft.com/keys/microsoft.asc" | \
                sudo tee /etc/yum.repos.d/azure-cli.repo
            
            # Install
            sudo yum install -y azure-cli
            ;;
        *)
            print_error "Unsupported OS: $OS. Please install Azure CLI manually."
            print_info "Visit: https://docs.microsoft.com/cli/azure/install-azure-cli"
            exit 1
            ;;
    esac
    
    print_info "Azure CLI installed successfully!"
    az version
}

# Install Docker if requested
if [ "$INSTALL_DOCKER" = true ]; then
    if command -v docker &> /dev/null; then
        print_info "Docker is already installed: $(docker --version)"
    else
        install_docker
    fi
fi

# Install Azure CLI if requested
if [ "$INSTALL_AZCLI" = true ]; then
    if command -v az &> /dev/null; then
        print_info "Azure CLI is already installed: $(az version -o tsv | head -n1)"
    else
        install_azcli
    fi
fi

# Check if docker is installed
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    echo ""
    print_info "Run with --install-docker flag to install automatically:"
    echo "  bash quick-container.sh --install-docker"
    echo ""
    print_info "Or install manually:"
    echo ""
    print_info "On Ubuntu/Debian:"
    echo "  sudo apt update && sudo apt install docker.io -y"
    echo ""
    print_info "On Azure Linux:"
    echo "  sudo tdnf update && sudo tdnf install -y moby-engine moby-cli"
    exit 1
fi

# Check if docker service is running
if ! docker info &> /dev/null; then
    print_warning "Docker service is not running or you don't have permission to access it."
    print_info "Try starting Docker service:"
    echo "  sudo systemctl start docker"
    echo ""
    print_info "Or add your user to the docker group:"
    echo "  sudo usermod -aG docker \$USER"
    echo "  newgrp docker"
    exit 1
fi

# Determine if runbook is external file or internal path
RUNBOOK_IS_EXTERNAL=false
if [ -n "$RUNBOOK" ]; then
    if [ -f "$RUNBOOK" ]; then
        # External file exists
        RUNBOOK_IS_EXTERNAL=true
        print_info "Using external runbook file: $RUNBOOK"
    else
        # Assume it's an internal container path
        print_info "Using container internal runbook: $RUNBOOK"
    fi
fi

# Pull the latest image (only if --pull is specified)
if [ "$PULL_IMAGE" = true ]; then
    print_info "Pulling latest LISA Docker image: $LISA_IMAGE"
    if ! docker pull "$LISA_IMAGE"; then
        print_error "Failed to pull Docker image: $LISA_IMAGE"
        exit 1
    fi
    print_info "Successfully pulled image: $LISA_IMAGE"
else
    print_info "Using local image (if available): $LISA_IMAGE"
    print_info "Tip: Use --pull to get the latest image"
    # Verify local image exists, if not try to pull
    if ! docker image inspect "$LISA_IMAGE" &> /dev/null; then
        print_warning "Local image not found: $LISA_IMAGE"
        print_info "Attempting to pull the image..."
        if ! docker pull "$LISA_IMAGE"; then
            print_error "Failed to pull Docker image: $LISA_IMAGE"
            exit 1
        fi
        print_info "Successfully pulled image: $LISA_IMAGE"
    fi
fi

# Build docker run command using arrays to handle spaces and special characters properly
# Initialize the command array
DOCKER_CMD_ARRAY=("docker" "run")

# Add remove flag if requested
if [ "$REMOVE_CONTAINER" = true ]; then
    DOCKER_CMD_ARRAY+=("--rm")
fi

# Add mount if specified (validate early)
if [ -n "$MOUNT_PATH" ]; then
    if [ ! -d "$MOUNT_PATH" ]; then
        print_error "Mount path does not exist: $MOUNT_PATH"
        exit 1
    fi
fi

# Add command based on mode
if [ "$INTERACTIVE" = true ]; then
    print_info "Starting interactive shell in LISA container..."
    if [ -n "$MOUNT_PATH" ]; then
        print_info "Mounting local directory: $MOUNT_PATH -> /workspace"
    fi
    
    # Add interactive flags
    DOCKER_CMD_ARRAY+=("-it")
    DOCKER_CMD_ARRAY+=("--name" "$CONTAINER_NAME")
    
    # Add mount if specified
    if [ -n "$MOUNT_PATH" ]; then
        DOCKER_CMD_ARRAY+=("-v" "$MOUNT_PATH:/workspace")
    fi
    
    # Add extra arguments (split by spaces - user responsibility to quote properly)
    if [ -n "$EXTRA_ARGS" ]; then
        read -r -a extra_args_array <<< "$EXTRA_ARGS"
        DOCKER_CMD_ARRAY+=("${extra_args_array[@]}")
    fi
    
    # Add image and command
    DOCKER_CMD_ARRAY+=("$LISA_IMAGE" "/bin/bash")
else
    print_info "Running LISA with runbook: $RUNBOOK"
    
    # Create log directory if it doesn't exist
    if [ -n "$LOG_PATH" ]; then
        mkdir -p "$LOG_PATH"
        LOG_PATH_ABS=$(realpath "$LOG_PATH")
        print_info "LISA logs will be saved to: $LOG_PATH_ABS"
    fi
    
    # Add non-interactive flag
    DOCKER_CMD_ARRAY+=("-i")
    DOCKER_CMD_ARRAY+=("--name" "$CONTAINER_NAME")
    
    # Mount external runbook if it's a file
    if [ "$RUNBOOK_IS_EXTERNAL" = true ]; then
        RUNBOOK_ABS=$(realpath "$RUNBOOK")
        RUNBOOK_DIR=$(dirname "$RUNBOOK_ABS")
        RUNBOOK_FILE=$(basename "$RUNBOOK_ABS")
        DOCKER_CMD_ARRAY+=("-v" "$RUNBOOK_DIR:/runbook")
        RUNBOOK_PATH="/runbook/$RUNBOOK_FILE"
    else
        # Use internal container path as-is
        RUNBOOK_PATH="$RUNBOOK"
    fi
    
    # Add mount if specified
    if [ -n "$MOUNT_PATH" ]; then
        DOCKER_CMD_ARRAY+=("-v" "$MOUNT_PATH:/workspace")
    fi
    
    # Mount log directory
    if [ -n "$LOG_PATH" ]; then
        DOCKER_CMD_ARRAY+=("-v" "$LOG_PATH_ABS:/app/lisa/runtime")
    fi
    
    # Add extra arguments (split by spaces - user responsibility to quote properly)
    if [ -n "$EXTRA_ARGS" ]; then
        read -r -a extra_args_array <<< "$EXTRA_ARGS"
        DOCKER_CMD_ARRAY+=("${extra_args_array[@]}")
    fi
    
    # Add image
    DOCKER_CMD_ARRAY+=("$LISA_IMAGE")
    
    # Add LISA command with runbook
    DOCKER_CMD_ARRAY+=("lisa" "-r" "$RUNBOOK_PATH")
    
    # Add LISA variables
    for var in "${LISA_VARIABLES[@]}"; do
        DOCKER_CMD_ARRAY+=("-v" "$var")
    done
fi

# Show the command being executed (mask sensitive values)
print_info "Executing Docker command:"

# Build a display version of the command with secrets masked
DOCKER_CMD_DISPLAY=""
for arg in "${DOCKER_CMD_ARRAY[@]}"; do
    # Mask sensitive values (tokens, secrets, passwords, keys)
    if [[ "$arg" =~ (token|secret|password|key|credential).*: ]]; then
        # Extract the key part before the colon and mask the value
        masked_arg="${arg%%:*}:***MASKED***"
        DOCKER_CMD_DISPLAY="$DOCKER_CMD_DISPLAY $masked_arg"
    elif [[ "$arg" =~ ^eyJ ]]; then
        # Mask JWT tokens (they typically start with eyJ)
        DOCKER_CMD_DISPLAY="$DOCKER_CMD_DISPLAY ***MASKED_TOKEN***"
    else
        DOCKER_CMD_DISPLAY="$DOCKER_CMD_DISPLAY $arg"
    fi
done
echo " $DOCKER_CMD_DISPLAY"
echo ""

# Execute the command using the array (properly handles spaces and special characters)
"${DOCKER_CMD_ARRAY[@]}"

# Check exit code
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    print_info "LISA container completed successfully"
    if [ -n "$LOG_PATH" ] && [ "$INTERACTIVE" = false ]; then
        print_info "Logs saved to: $LOG_PATH_ABS"
        if [ -d "$LOG_PATH_ABS/log" ]; then
            print_info "Test logs: $LOG_PATH_ABS/log/"
        fi
    fi
else
    print_error "LISA container exited with code: $EXIT_CODE"
    if [ -n "$LOG_PATH" ] && [ "$INTERACTIVE" = false ]; then
        print_info "Check logs at: $LOG_PATH_ABS"
    fi
    exit $EXIT_CODE
fi

