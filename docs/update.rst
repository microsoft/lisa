Updating LISA
=============

Once LISA has been successfully installed on your computer,
the steps below can be used to keep it updated.

To update the the local repo, ensure you are in the main branch and run


.. code:: bash

    git pull

If you installed LISA, reinstall to get the latest version.

.. code:: bash

   python3 -m pip install .[azure,libvirt]


If you're using a virtual environment, recreate the virtual environment.

.. code:: bash

    nox -vs dev


