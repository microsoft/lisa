Command line reference
======================

-  `Common arguments <#common-arguments>`__

   -  `-r, –runbook <#-r-runbook>`__
   -  `-d, –debug <#-d-debug>`__
   -  `-h, –help <#-h-help>`__
   -  `-v, –variable <#-v-variable>`__

-  `run <#run>`__
-  `check <#check>`__
-  `list <#list>`__

Common arguments
----------------

-r, –runbook
~~~~~~~~~~~~

Specify the path of `runbook <runbook.html>`__. It can be an absolute
path or a relative path. This parameter is required in every run other
than run with -h.

.. code:: sh

   lisa -r ./microsoft/runbook/azure.yml

-d, –debug
~~~~~~~~~~

By default, the console will display INFO or higher level logs, but will
not display DEBUG level logs. This option enables the console to output
DEBUG level logs. Note the log file will not be affected by this setting
and will always contain the DEBUG level messages.

.. code:: sh

   lisa -d

-h, –help
~~~~~~~~~

Show help messages.

.. code:: sh

   lisa -h

-v, –variable
~~~~~~~~~~~~~

Define one or more variables in the format of ``name:value``, which will
overwrite the value in the YAML file. It can support secret values in
the format of ``s:name:value``.

.. code:: sh

   lisa -r ./microsoft/runbook/azure.yml -v location:westus2 -v "gallery_image:Canonical UbuntuServer 18.04-LTS Latest"

run
---

An optional command since it is the default operation. The following two
lines perform the same operation.

.. code:: sh

   lisa run -r ./microsoft/runbook/azure.yml

.. code:: sh

   lisa -r ./microsoft/runbook/azure.yml

check
-----

Check whether the specified YAML file and variables are valid.

.. code:: sh

   lisa check -r ./microsoft/runbook/azure.yml

list
----

Output information of this run.

-  ``-t`` or ``--type`` specifies the information type. It supports
   ``case``.

   .. code:: sh

      lisa list -r ./microsoft/runbook/local.yml -v tier:0 -t case

-  With ``-a`` or ``--all``, it will ignore test case selection, and
   display all test cases.

   .. code:: sh

      lisa list -r ./microsoft/runbook/local.yml -v tier:0 -t case -a
