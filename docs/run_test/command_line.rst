Command line reference
======================

-  `Common arguments <#common-arguments>`__

   -  `-r, --runbook <#r-runbook>`__
   -  `-d, --debug <#d-debug>`__
   -  `-l, --log_path <#l-log_path>`__
   -  `-w, --working_path <#w-working_path>`__
   -  `-i, --id <#i-id>`__
   -  `-h, --help <#h-help>`__
   -  `-v, --variable <#v-variable>`__

-  `run <#run>`__
-  `check <#check>`__
-  `list <#list>`__

Common arguments
----------------

-r, --runbook
~~~~~~~~~~~~~

Specify the path of :doc:`runbook <runbook>`. It can be an absolute
path or a relative path. This parameter is required in every run other
than run with -h.

.. code:: sh

   lisa -r ./microsoft/runbook/azure.yml

-d, --debug
~~~~~~~~~~~

By default, the console will display INFO or higher level logs, but will
not display DEBUG level logs. This option enables the console to output
DEBUG level logs. Note the log file will not be affected by this setting
and will always contain the DEBUG level messages.

.. code:: sh

   lisa -d

-l, --log_path
~~~~~~~~~~~~~~

By default, the runtime/log will be used to storage logs. In case it needs to
save log to customized path, specify a relative or absolute path to change the
default path.

.. code:: sh

   lisa -l new_path

-w, --working_path
~~~~~~~~~~~~~~~~~~

By default, the runtime/working will be used to storage working files. In case
it needs to use a customized working path, specify a relative or absolute path
to change the default path.

.. code:: sh

   lisa -w new_path

-i, --id
~~~~~~~~

By default, the LISA generate a string like "20220226/20220226-075916-054". It
uses as log path of this run. The last part of the name "20220226-075916-054" is
used as ID of this run. In Azure, it will be used in resource_group_name. In
some cases, the name may be conflict in a global place. This argument can
overwrite the default behavior, so it has a chance to create an unique name. If
it contains multiple parts of path, the last part will be used as run id. The
whole path will be taken into log path.

.. code:: sh

   lisa -i new_id

-h, --help
~~~~~~~~~~

Show help messages.

.. code:: sh

   lisa -h

-v, --variable
~~~~~~~~~~~~~~

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
