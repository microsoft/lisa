"""A plugin for creating, using, and managing remote targets.

The abstract base `Target` class provides an interface for adding
platform-specific support through sub-classes. A usable reference
implementation is the `Azure` class. A class for testing on the local
system is the `Local` class. Sub-classes can be implemented in a
`conftest.py` file and will be found automatically.

Tests can request access to a target through the function-scoped
`target` Pytest fixture, which returns an instance based on the
targets listed in a `playbook.yaml` file. The fixture is parameterized
across the list of provided targets. For example:

    targets:
      - name: Debian
        platform: Azure
        image: Debian:debian-10:10:latest
      - name: Ubuntu
        platform: Azure
        image: Canonical:UbuntuServer:18.04-LTS:latest
      - name: OpenSUSE
        platform: Azure
        image: SUSE:openSUSE-Leap:42.3:latest

Will run all selected tests against each target. The `pool` fixture is
session-scoped and used by the `target` fixture to efficiently re-use
deployed targets.

"""
import pytest

# Provide common types in the package's namespace.
from target.azure import Azure
from target.target import SSH, Target

# NOTE: This is mostly to avoid “imported but not used.”
__all__ = ["Azure", "Target", "SSH"]

# See https://docs.pytest.org/en/stable/writing_plugins.html#assertion-rewriting
pytest.register_assert_rewrite("pytest_target.azure", "pytest_target.target")
