# Install LISA on Linux

- [Install Python on Linux](#install-python-on-linux)
- [Install dependencies on Linux](#install-dependencies-on-linux)
- [Clone code](#clone-code)
- [Install Poetry on Linux](#install-poetry-on-linux)
- [Verify installation](#verify-installation)
- [FAQ and Troubleshooting](#faq-and-troubleshooting)

## Install Python on Linux

LISA has been tested on [Python 3.8 64 bits](https://www.python.org/). The
latest version of Python 3 is recommended. If you found LISA is not compatible
with higher version Python, [please file an
issue](https://github.com/microsoft/lisa/issues/new).

Run following commands to install Python 3.8 in Ubuntu 20.04.

```bash
sudo apt update
sudo apt install software-properties-common -y
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt install python3.8 python3.8-dev -y
```

## Install dependencies on Linux

In Linux, for example, on Ubuntu 20.04, please use the command below to install
the dependencies:

```bash
sudo apt install git gcc libgirepository1.0-dev libcairo2-dev virtualenv python3-pip -y
pip3 install virtualenv
```

## Clone code

```sh
git clone https://github.com/microsoft/lisa.git
cd lisa
```

## Install Poetry on Linux

Poetry is used to manage Python dependencies of LISA.

:warning: Please enter the root folder of LISA source code to run following
commands to install poetry, since Poetry manages dependencies by the working
folder.

```bash
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/install-poetry.py | python3 -
```

After running this, you should see `Add export
PATH="/home/YOURUSERNAME/.local/bin:$PATH" to your shell configuration file` on
the console. Then do

```bash
source $HOME/.profile
poetry install
```

## Verify installation

`lisa.sh` is provided in Linux to wrap `Poetry` for you to run LISA test.

In Linux, you could create an alias for this simple script. For example, add
below line to add to `.bashrc`:

```bash
alias lisa="./lisa.sh"
```

With no argument specified, LISA will run some sample test cases with the
default runbook (`examples/runbook/hello_world.yml`) on your local computer. In
the root folder of LISA, you can run this command to verify your local LISA
environment setup. This test will not modify your computer.

```bash
lisa
```

## FAQ and Troubleshooting

If there's any problem during the installation, please refer to [FAQ and
troubleshooting](troubleshooting.md).