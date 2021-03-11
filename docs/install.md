# Install LISA

- [Prerequisites](#prerequisites)
- [Install Python](#install-python)
- [Install dependencies](#install-dependencies)
- [Clone code](#clone-code)
- [Install Poetry and Python dependencies](#install-poetry-and-python-dependencies)
  - [Install Poetry in Linux](#install-poetry-in-linux)
  - [Install Poetry in Windows](#install-poetry-in-windows)
- [FAQ and Troubleshooting](#faq-and-troubleshooting)

LISA supports to run on Windows and Linux. Follow below steps to install LISA from source code.

## Prerequisites

- Can access the tested platform, like Azure, Hyper-V, or else. It recommends having good bandwidth and low network latency.
- At least 2 CPU cores and 4GB memory.

## Install Python

Install latest [Python 3.8 64 bits](https://www.python.org/). If there are Python installed already, please make sure effective Python's version is 3.8 64 bits or above.

LISA is developed and tested with Python 3.8 (64 bit). The latest version of Python 3.8 is recommended. If LISA is not compatible with higher Python version, [file an issue](https://github.com/microsoft/lisa/issues/new) to us.

## Install dependencies

Since LISA is installed from source, `git` is necessary. And some packages need to be built, so the build tools are also needed.

In Linux, it needs `git` and `gcc`. Below is depended packages on Ubuntu.

```bash
sudo apt install git gcc
```

In Windows, you need to install [git](https://git-scm.com/downloads) and [Visual C++ redistributable package](https://aka.ms/vs/16/release/vc_redist.x64.exe)

## Clone code

Open a terminal window, and enter the folder, which uses to put lisa code. If you want to use the latest version, checkout the main branch.

```sh
git clone https://github.com/microsoft/lisa.git
cd lisa
git checkout main
```

## Install Poetry and Python dependencies

Poetry is used to manage Python dependencies of LISA. Execute corresponding script to install Poetry.

Note, it's important to enter LISA's folder to run below command, since Poetry manages dependencies by the working folder.

### Install Poetry in Linux

```bash
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python3 -
source $HOME/.poetry/env
poetry install
```

### Install Poetry in Windows

Enter the PowerShell command prompt and execute,

```powershell
(Invoke-WebRequest -Uri https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py -UseBasicParsing).Content | python -
# the path can be added to system, so it applies to every terminal.
$env:PATH += ";$env:USERPROFILE\.poetry\bin"
poetry install
```

## FAQ and Troubleshooting

Refer to [FQA and troubleshooting](troubleshooting.md).
