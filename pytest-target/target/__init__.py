# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""A plugin for creating, using, and managing remote targets.

The abstract base :py:class:`~target.target.Target` class provides an
interface for adding platform-specific support through sub-classes. A
usable reference implementation is the
:py:class:`~target.azure.AzureCLI` class. A class for just connecting
over SSH is the :py:class:`~target.target.SSH` Sub-classes can be
implemented in a ``conftest.py`` file and will be found automatically.

Tests can request access to a target through the function-scoped
`target` Pytest fixture, which returns an instance based on the
targets listed in a `playbook.yaml` file. The fixture is parameterized
across the list of provided targets. For example:

.. code-block:: yaml

   platforms:
     AzureCLI:
       sku: Standard_DS2_v2

   targets:
     - name: Debian
       platform: AzureCLI
       image: Debian:debian-10:10:latest

     - name: Ubuntu
       platform: AzureCLI
       image: Canonical:UbuntuServer:18.04-LTS:latest

Will run all selected tests against each target. The pool of targets
can be cached between runs with ``--keep-targets``.

"""
import pytest

# Provide common types in the package's namespace.
from target.azure import AzureCLI
from target.target import SSH, Target

# NOTE: This is mostly to avoid “imported but not used.”
__all__ = ["AzureCLI", "Target", "SSH"]

# See https://docs.pytest.org/en/stable/writing_plugins.html#assertion-rewriting
pytest.register_assert_rewrite("pytest_target.azure", "pytest_target.target")
