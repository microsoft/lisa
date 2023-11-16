Extra Dependencies
==================

What are extras?
----------------

Python has a concept of `Extras`, which are groups of dependencies that can be
with a package to provide additional functionality.

To `install extras`_, simply include the name(s) in square brackets after the
package name.

.. code:: bash

   pip install lisa[azure,libvirt]

LISA's extras
-------------

LISA has several supported extra dependency groups.

aws
    Provides dependencies for running LISA on Amazon Web Services

azure
    Provides dependencies for running LISA on Microsoft Azure

libvirt
    Provides dependencies for running LISA on libvirt-managed hypervisors


.. _install extras: https://packaging.python.org/en/latest/tutorials/installing-packages/#installing-extras
