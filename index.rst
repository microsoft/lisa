Linux Integration Services Automation
=====================================

|LISA/Pytest CI Workflow| |Code Style: black|

LISA is a Linux test automation framework with built-in test cases to
verify the quality of Linux distributions on multiple platforms (such
as Azure, Hyper-V, and bare metal). It is an opinionated collection of
custom `Pytest <https://docs.pytest.org/en/stable/>`_ plugins,
configurations, and tests. See the :doc:`technical specification
document <DESIGN>` for details, and the `GitHub repository`_ for
sources.

.. _GitHub repository: https://github.com/microsoft/lisa/tree/andschwa/pytest

.. toctree::
   :maxdepth: 3
   :caption: Documentation
   :hidden:

   Usage <USAGE>
   Design <DESIGN>
   Contributing <CONTRIBUTING>
   Code of Conduct <CODE_OF_CONDUCT>

Getting Started
---------------

See the :doc:`usage document <USAGE>` for how to setup the
requirements, run tests, and write new tests.

Python Modules
--------------

See the :doc:`technical specification document <DESIGN>` for design
details, and see the below table for auto-generated API documentation
of the framework.

.. autosummary::
   :toctree: modules
   :caption: API
   :recursive:

   lisa
   target
   playbook

Contributing
------------

See the :doc:`contributing guidelines <CONTRIBUTING>` for developer
information!

.. |LISA/Pytest CI Workflow| image:: https://github.com/microsoft/lisa/workflows/LISA/Pytest%20CI%20Workflow/badge.svg?branch=andschwa%2Fpytest
   :target: https://github.com/microsoft/lisa/actions?query=workflow%3A%22LISA%2FPytest+CI+Workflow%22
.. |Code Style: black| image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/psf/black
