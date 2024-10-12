FROM mcr.microsoft.com/cbl-mariner/base/core:2.0

# Set the working directory
WORKDIR /app

# Install necessary system dependencies
RUN tdnf update -y
RUN tdnf install -y git gcc gobject-introspection-devel cairo-gobject cairo-devel pkg-config libvirt-devel python3-devel python3-pip python3-virtualenv build-essential cairo-gobject-devel curl ca-certificates

# Clone the latest release of LISA from the GitHub repository
RUN git clone --branch $(curl --silent "https://api.github.com/repos/microsoft/lisa/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/') https://github.com/microsoft/lisa.git /app/lisa

# Install Python dependencies for LISA
RUN python3 -m pip install --upgrade pip
WORKDIR /app/lisa
RUN python3 -m pip install --editable .[azure,libvirt,baremetal] --config-settings editable_mode=compat
RUN ln -fs /app/.local/bin/lisa /bin/lisa
