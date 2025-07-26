Runbook Reference
=================

-  `What is a runbook <#what-is-a-runbook>`__
-  `How-to <#how-to>`__

   -  `Configure Azure deployment <#configure-azure-deployment>`__
   -  `Select and set test cases <#select-and-set-test-cases>`__
   -  `Use variable and secrets <#use-variable-and-secrets>`__
   -  `Use partial runbook <#use-partial-runbook>`__
   -  `Use extensions <#use-extensions>`__

-  `Reference <#reference>`__

   -  `name <#name>`__
   -  `test_project <#test-project>`__
   -  `test_pass <#test-pass>`__
   -  `tags <#tags>`__
   -  `concurrency <#concurrency>`__
   -  `include <#include>`__

      -  `path <#path>`__

   -  `extension <#extension>`__

      -  `name <#name-1>`__
      -  `path <#path-1>`__

   -  `variable <#variable>`__

      -  `is_case_visible <#is-case-visible>`__
      -  `is_secret <#is-secret>`__
      -  `file <#file>`__
      -  `name <#name-2>`__
      -  `value <#value>`__

   -  `transformer <#transformer>`__

      -  `type <#type>`__
      -  `name <#name-3>`__
      -  `prefix <#prefix>`__
      -  `depends_on <#depends-on>`__
      -  `rename <#rename>`__

   -  `combinator <#combinator>`__

      -  `grid combinator <#grid-combinator>`__

         -  `items <#items>`__

      -  `batch combinator <#batch-combinator>`__

         -  `items <#items-1>`__
      -   `bisect combinator <#bisect-combinator>`__

   -  `notifier <#notifier>`__

      -  `console <#console>`__

         -  `log_level <#log-level>`__

      -  `html <#html>`__

         -  `path <#path-2>`__
         -  `auto_open <#auto-open>`__

      -  `junit <#junit>`__

         -  `path <#path-3>`__
         -  `include_subtest <#include-subtest>`__
         -  `append_message_id <#append-message-id>`__

   -  `environment <#environment>`__

      -  `retry <#retry>`__

      -  `environments <#environments>`__

         -  `name <#name-4>`__
         -  `topology <#topology>`__
         -  `nodes <#nodes>`__
         -  `nodes_requirement <#nodes-requirement>`__

            -  `type <#type-1>`__

   -  `platform <#platform>`__
   -  `testcase <#testcase>`__

      -  `criteria <#criteria>`__

What is a runbook
-----------------

In simple terms:
   `The **runbook** contains all the configurations of LISA operation. It keeps
   you from lengthy command-line commands and makes it easy to adjust
   configurations.`

See :ref:`write_test/concepts:runbook` for further knowledge.

How-to
------

Configure Azure deployment
~~~~~~~~~~~~~~~~~~~~~~~~~~

Below section is for running cases on Azure platform, it specifies:

-  admin_private_key_file: the private key file to access the Azure VM. (Optional)
-  subscription_id: Azure VM is created under this subscription.
-  azcopy_path: the installation path of the AzCopy tool on the machine where LISA is installed. It speeds up copying VHDs between Azure storage accounts. (Optional)

.. code:: yaml

   platform:
     - type: azure
       admin_private_key_file: $(admin_private_key_file)
       azure:
         subscription_id: $(subscription_id)
         azcopy_path: $(azcopy_path)

Select and set test cases
~~~~~~~~~~~~~~~~~~~~~~~~~

Below section is to specify P0 and P1 test cases excluding case with
name ``hello``.

.. code:: yaml

   testcase:
     - criteria:
         priority: [0, 1]
     - criteria:
         name: hello
       select_action: exclude

Use variable and secrets
~~~~~~~~~~~~~~~~~~~~~~~~

Below section is to specify the variable in name/value format. We can
use this variable in other field in this format ``$(location)``.

.. code:: yaml

   variable:
     - name: location
       value: westus3

The value of variable passed from command line will override the value
in runbook yaml file.

.. code:: bash

   lisa -r sample.yml -v "location:westus3"

Below section is to specify the path of yaml file which stores the
secret values.

.. code:: yaml

   variable:
     - file: secret.yml

Content of secret.yml.

.. code:: yaml

   subscription_id:
     value: replace_your_subscription_id_here
     is_secret: true
     mask: guid

Use partial runbook
~~~~~~~~~~~~~~~~~~~

Below three yaml files will be loaded in this sequence.

.. code:: bash

   loading runbook sample.yml
   |-- loading include tier.yml
   |   |-- loading include t0.yml

The variable values in the included yaml file(s) will be overridden by
the including yaml file(s). The relative path is always relative to
the including yaml file.

Part of sample.yml

.. code:: yaml

   include:
     - path: ./tier.yml

Part of tier.yml.

.. code:: yaml

   include:
     - path: ./t$(tier).yml
   variable:
     - name: tier
       value: 0

Part of t0.yml.

.. code:: yaml

   testcase:
     - criteria:
         priority: 0

Use extensions
~~~~~~~~~~~~~~

Below section is to specify path of extensions, the extensions are
modules for test cases or extended features.

.. code:: yaml

   extension:
     - name: extended_features
       path: ../../extensions
     - ../../lisa/microsoft/testsuites/core

Use transformers
~~~~~~~~~~~~~~~~

Transformers are executed one by one. The order is decided by their
dependencies. If there is no dependencies, their order in runbook affects the
execution order.

Below transformer shows how to deploy a VM in Azure, and export it to a VHD.
Before the exporting, other transformers can be added, like install kernel.

.. code:: yaml

   transformer:
   - type: azure_deploy
     requirement:
       azure:
         marketplace: redhat rhel 7_9 7.9.2021051701
   - type: azure_vhd
     resource_group_name: $(azure_deploy_resource_group_name)
     rename:
       azure_vhd_url: vhd
   - type: azure_delete
     resource_group_name: $(azure_deploy_resource_group_name)

Below is the transformer to build kernel from source code and patches.

.. code:: yaml

   transformer:
   - type: azure_deploy
     requirement:
       azure:
         marketplace: $(marketplace_image)
       core_count: 16
     enabled: true
   - type: kernel_installer
     connection:
       address: $(azure_deploy_address)
       private_key_file: $(admin_private_key_file)
     installer:
       type: source
       location:
         type: repo
         path: /mnt/code
         ref: tags/v4.9.184
       modifier:
         - type: patch
           repo: https://github.com/microsoft/azure-linux-kernel.git
           file_pattern: Patches_Following_Mainline_History/4.9.184/*.patch

Reference
---------

name
~~~~

type: str, optional, default is “not_named”

Part of the test run name. This name will be used to group results and
put it in title of the html report, also the created resources' name
contains this specified str.

.. code:: yaml

   name: Azure Default

test_project
~~~~~~~~~~~~

type: str, optional, default is empty

The project name of this test run. This name will be used to group test
results in html, it also shows up in notifier message.

.. code:: yaml

   test_project: Azure Image Weekly Testing

test_pass
~~~~~~~~~

type: str, optional, default is empty

The test pass name of this test run. This name combined with test
project name will be used to group test results in html report, it also
shows up in notifier message.

.. code:: yaml

   test_pass: bvt testing

tags
~~~~

type: list of str, optional, default is empty

The tags of the test run. This name combined with test project name and
test pass name will be used to group test results in html report, it
also shows up in notifier message.

.. code:: yaml

   tags:
     - test
     - bvt

concurrency
~~~~~~~~~~~

type: int, optional, default is 1.

The number of concurrent running environments.

include
~~~~~~~

type: list of path, optional, default is empty

Share runbook parts for similar runs, including the shared content via
that yaml primitive.

path
^^^^

It can be absolute or relative path of current runbook.

extension
~~~~~~~~~

type: list of path str or name/path pairs, optional, default: empty

The path and the name of the modules, we can also just specify the
extension path directly.

.. code:: yaml

   extension:
     - name: ms
       path: ../../extensions

.. _name-1:

name
^^^^

type: str, optional, default is empty

Each extension can be specified a name. With the name, one extension can
reference another one, using above example extension, in code we can
reference it like this way ms.submodule.

.. _path-1:

path
^^^^

type: str, optional, default is empty

Path of extension, it can be absolute or relative path of current
runbook file.

variable
~~~~~~~~

type: list of path str or name/value pairs, optional, default: empty

Used to support variables in other fields.

The values pass from command line has the highest priority, with below
example, any places use ``${subscription_id}`` will be replaced with
value ``subscription id B``.

.. code:: bash

   lisa -r ./microsoft/runbook/azure.yml -v "subscription_id:<subscription id A>"

.. code:: yaml

   variable:
     - name: subscription_id
       value: subscription id B

The variable values in the runbook have higher priority than the same variables
defined in any included runbook file. Thus, ``${location}`` will be replaced with
value ``northeurope`` in the following example.

.. code:: yaml

   include:
     - path: tier.yml
   variable:
     - name: location
       value: northeurope

tier.yml

.. code:: yaml

   variable:
     - name: location
       value: westus3

The later defined variables values in runbook have higher priority than
the same variables previous defined. ``${location}`` will be replaced
with value ``northeurope``.

.. code:: yaml

   variable:
     - name: location
       value: westus3
     - name: location
       value: northeurope

is_case_visible
^^^^^^^^^^^^^^^

type: bool, optional, default is False.

When set to True, the value of this variable will be passed to the testcases,
such as ``perf_nested_kvm_storage_singledisk`` which requires information
about nested image.

is_secret
^^^^^^^^^

type: bool, optional, default is False.

When set to True, the value of this variable will be masked in log and
other output information.

Recommend to use secret file or env variable. It's not recommended to
specify secret value in runbook directly.

file
^^^^

type: list of str, optional, default: empty

Specify path of other yml files which define variables.

.. _name-2:

name
^^^^

type: str, optional, default is empty.

Variable name.

value
^^^^^

type: str, optional, default is empty

Value of the paired variable.

transformer
~~~~~~~~~~~

type: list of Transformer, default is empty

type
^^^^

type: str, required, the type of transformer. See `transformers
<https://github.com/microsoft/lisa/tree/main/lisa/transformers>`__ for all
transformers.

See :doc:`documentation for transformers<transformers>`.

.. _name-3:

name
^^^^

type: str, optional, default is the ``type``.

Unique name of the transformer. It's depended by other transformers. If
it's not specified, it will use the ``type`` field. But if there are two
transformers with the same type, one of them should have name at least.

prefix
^^^^^^

type: str, optional, default is the ``name``.

The prefix of generated variables from this transformer. If it's not
specified, it will use the ``name`` field.

depends_on
^^^^^^^^^^

type: list of str, optional, default is None.

The depended transformers. The depended transformers will run before
this one.

rename
^^^^^^

type: Dict[str, str], optional, default is None.

The variables, which need to be renamed. If the variable exists already,
its value will be overwritten by the transformer. For example,
``["to_list_image", "image"]`` means change the variable name
``to_list_image`` to ``image``. The original variable name must exist in
the output variables of the transformer.

.. _combinator:

combinator
~~~~~~~~~~

type: str, required.

The type of combinator, for example, ``grid`` or ``batch``.

grid combinator
^^^^^^^^^^^^^^^

items
'''''

type: List[Variable], required.

The variables which are in the matrix. Each variable must be a list.

For example,

.. code:: yaml

   - type: grid
     items:
     - name: image
       value:
         - Ubuntu
         - CentOs
     - name: vm_size
       value:
         - Standard_DS2_v2
         - Standard_DS3_v2
         - Standard_DS4_v2

batch combinator
^^^^^^^^^^^^^^^^

.. _items-1:

items
'''''

type: List[Dict[str, Any]], required.

Specify batches of variables. Each batch will run once.

For example,

.. code:: yaml

   - type: batch
     items:
     - image: Ubuntu
       vm_size: Standard_DS2_v2
     - image: Ubuntu
       vm_size: Standard_DS3_v2
     - image: CentOS
       vm_size: Standard_DS3_v2


bisect combinator
^^^^^^^^^^^^^^^^^

Specify a git repo url, the good commit and bad commit. The combinator
performs bisect operations on VM specified under 'connection'.

The runbook will be iterated until the bisect operations completes.

For example,

.. code:: yaml

  combinator:
    type: git_bisect
    repo: $(repo_url)
    bad_commit: $(bad_commit)
    good_commit: $(good_commit)
    connection:
      address: $(bisect_vm_address)
      private_key_file: $(admin_private_key_file)

Refer `Sample runbook <https://github.com/microsoft/lisa/blob/main/microsoft/runbook/examples/git_bisect.yml>`__

notifier
~~~~~~~~

Receive messages during the test run and output them somewhere.

console
^^^^^^^

One of notifier type. It outputs messages to the console and file log
and demonstrates how to implement notification procedures.

Example of console notifier:

.. code:: yaml

   notifier:
     - type: console
       log_level: INFO

log_level
'''''''''

type: str, optional, default: DEBUG, values: DEBUG, INFO, WARNING…

Set log level of notification messages.

html
^^^^

Output test results in html format. It can be used for local development
or as the body of an email.

.. _path-2:

path
''''

type: str, optional, default: lisa.html

Specify the output file name and path.

auto_open
'''''''''

type: bool, optional, default: False

When set to True, the html will be opened in the browser after
completion. Useful in local run.

Example of html notifier:

.. code:: yaml

   notifier:
     - type: html
       path: ./lisa.html
       auto_open: true

junit
^^^^^

Output test results in JUnit XML format. The generated XML file can be used
for integration with CI/CD systems, dashboards, and other tools that consume
JUnit test results.

.. _path-3:

path
''''

type: str, optional, default: lisa.junit.xml

Specify the output file name and path for the JUnit XML report.

include_subtest
'''''''''''''''

type: bool, optional, default: True

When set to True, subtests will be included as separate test cases in the
JUnit XML output. When set to False, only main test cases are included.

append_message_id
'''''''''''''''''

type: bool, optional, default: True

When set to True, the message ID will be appended to test case names in the
format "test_name (message_id)". This is useful when using combinators to
distinguish multiple test runs of the same test case. When set to False,
only the base test case name is used.

Example of junit notifier:

.. code:: yaml

   notifier:
     - type: junit
       path: ./results.xml
       include_subtest: true
       append_message_id: false

environment
~~~~~~~~~~~

List of environments. For more information, refer to
:ref:`write_test/concepts:node and environment`.

retry
^^^^^^^^^^^^

Number of retry attempts for failed deployments, default value is 0.

environments
^^^^^^^^^^^^

List of test run environment.

.. _name-4:

name
''''

type: str, optional, default is empty

The name of the environment.

topology
''''''''

type: str, optional, default is “subnet”

The topology of the environment, current only support value “subnet”.

nodes
'''''

List of node, it can be a virtual machine on Azure or Hyper-V, bare metal or
others. For more information, refer to :ref:`write_test/concepts:node and
environment`.

nodes_requirement
'''''''''''''''''

List of testing required environments, by default node_count (default is
1), core_count (default is 1), memory_mb (default is 512 MB), data_disk_count
(default is 0), nic_count (default is 1), gpu_count (default is 0). The
node can be created once the node requirement is met.

.. _type-1:

type
    

type: str, optional, default value is “requirement”, supported values
are “requirement”, “remote”, “local”.

platform
~~~~~~~~

List of platform, default value is “ready”, current support values are
“ready”, “azure”.

testcase
~~~~~~~~

type: list of str, optional, default: lisa

Criteria to select cases.

criteria
^^^^^^^^

type: list of dictionary, optional, default is empty

Select test cases by area, category, name, priority or tags combined
with select action.

select_action can be “none”, “include”, “exclude”, “forceInclude” and
“forceExclude”, default value is “none”.

.. code:: yaml

   testcase:
     - criteria:
         priority: 0
       select_action: include
     - criteria:
         priority: 1
       select_action: exclude
