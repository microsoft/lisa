"""This file sets up custom plugins.

https://docs.pytest.org/en/stable/writing_plugins.html

"""
from pathlib import Path

pytest_plugins = "node_plugin"

LINUX_SCRIPTS = Path("../Testscripts/Linux")
