# LISAv3 via pytest-lisa

Basic instructions for testing the prototype:

```bash
# Install Poetry, make sure `poetry` is in your `PATH`
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python

# Install Azure CLI, make sure `az` is in your `PATH`
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Login and set subscription
az login
az account set -s <your subscription ID>

# Clone LISAv2 with the Pytest prototype
git clone -b pytest/main https://github.com/LIS/LISAv2.git
cd LISAv2

# Install Python packages
make setup

# Run some local demos
make test
make yaml

# Run a demo which deployes Azure resources
make smoke
```

See the [design document](DESIGN.md) for details.
