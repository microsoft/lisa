Run tests on different platforms
================================

-  `Run on Azure <#run-on-azure>`__

   *  `Use vhd <#use-vhd>`__
   *  `Use marketplace image <#use-marketplace-image>`__
   *  `Use shared image gallery <#use-shared-image-gallery>`__
   *  `Use existing deployment <#use-existing-deployment>`__
   *  `Set other Azure parameters <#set-other-azure-parameters>`__

-  `Run on Ready computers <#run-on-ready-computers>`__

-  `Run on Linux and QEMU <#run-on-linux-and-qemu>`__

-  `Run on AWS <#run-on-aws>`__

Run on Azure
------------

VM can be deployed on Azure using images from vhd, shared image
gallery or marketplace. If multiple types are specified, the first
non-empty type is picked in the following order :
vhd, shared image gallery and marketplace.

Use vhd
^^^^^^^

To run using vhd, add the following to runbook :

.. code:: yaml

   platform:
   - type: azure
      ...
      requirement:
         ...
         azure:
            ...
            vhd: "<VHD URL>"
            hyperv_generation: <1 or 2>

The ``<VHD URL>`` can either be a SAS url or a blob url. If it is a SAS url, the image is copied to the resource group: ``lisa_shared_resource``, storage
account: ``lisat{location}{subscription_id[last 8 digits]}`` and container:
``lisa-sas-copied`` in the subscription used to run LISA, which could potentially
increase the runtime. The copied VHD has to be manually deleted by the user.

If the selected VM Size's Hypervisor Generation is '2', hyperv_generation
parameter is necessary, and should be specified as 2.

Use marketplace image
^^^^^^^^^^^^^^^^^^^^^

To run using marketplace image, add the following to runbook:

.. code:: yaml

   platform:
   - type: azure
      ...
      requirement:
         ...
         azure:
            ...
            marketplace: "<Publisher> <Offer> <Sku> <Version>"

Use shared image gallery
^^^^^^^^^^^^^^^^^^^^^^^^

To run using shared image gallery, add the following to runbook if the shared
image gallery is in the same subscription that is used to run LISA :

.. code:: yaml

   platform:
   - type: azure
      ...
      requirement:
         ...
         azure:
            ...
            shared_gallery: "<image_gallery>/<image_definition>/<image_version>"

If the shared image gallery is in a different subscription, ``subscription_id``
needs to be specified. Ensure that the credential used to run LISA has access to
the shared image gallery.

.. code:: yaml

   platform:
   - type: azure
      ...
      requirement:
         ...
         azure:
            ...
            shared_gallery: "<subscription_id>/<image_gallery>/<image_definition>/<image_version>"

The remaining steps are same as outlined in
:doc:`Getting started with Azure <quick_run>`.

Use existing deployment
^^^^^^^^^^^^^^^^^^^^^^^

In addition to deploying a new Azure server and running tests, you can
skip the deployment phase and use existing resource group. This feature
is only available for Azure platform.

The advantage is that it can run all test cases of Azure. The shortage
is that the VM name is fixed, and it should be node-0, so each resource
group can put only one VM.

To use existing deployment, follow the steps below:

1. Start a run with the variable values set to following in the runbook:

.. code:: bash

   lisa -r <runbook> ..  -v deploy:true -v keep_environment:always -v resource_group_name:"<resource group name>"

2. After the run is completed, the resource group will be kept. You can
   use the same resource group name in the subsequent runs.

.. code:: bash

   lisa -r <runbook> .. -v deploy:false -v keep_environment:always -v resource_group_name:"<resource group name>

Set other Azure parameters
^^^^^^^^^^^^^^^^^^^^^^^^^^

The other parameters, like location, vm size, can be specified during
deployment.

.. code:: yaml

   platform:
   - type: azure
      ...
      virtual_network_resource_group: $(vnet_resource_group)
      virtual_network_name: $(vnet_name)
      subnet_prefix: $(subnet_name)
      requirement:
         ...
         azure:
            ...
            location: "<one or multiple locations, split by comma>"
            vm_size: "<vm size>"
            maximize_capability: "<true or false>"

* **virtual_network_resource_group**. Specify if an existing virtual network
  should be used. If `virtual_network_resource_group` is not provided, a virtual
  network will be created in the default resource group. If
  `virtual_network_resource_group` is provided, an existing virtual network will
  be used.
* **virtual_network_name**. Specify the desired virtual network name.  If 
  `virtual_network_resource_group` is not provided, a virtual network will be
  created and the resulting virtual network name will be
  `<virtual_network_name>`.  If `virtual_network_resource_group` is provided,
  an existing virtual network, with the name equal to `virtual_network_name`,
  will be used.
* **subnet_prefix**. Specify the desired subnet prefix.  If 
  `virtual_network_resource_group` is not provided, a virtual network and
  subnet will be created and the resulting subnets will look like 
  `<subnet_profile>0`, `<subnet_profile>1`, and so on.  If 
  `virtual_network_resource_group` is provided, an existing virtual network and
  subnet, with the name equal to `subnet_prefix`, will be used.
* **location**. Specify which locations is used to deploy VMs. It can be one or
  multiple locations. For example, westus3 or westus3,eastus. If multiple
  locations are specified, it means each environment deploys VMs in one of
  location. To test multiple locations together, the :ref:`combinator
  <combinator>` is needed.
* **vm_size**. Specify which vm_size is used to deploy.
* **maximize_capability**. True means to ignore test requirement, and try best to
  run all test cases. Notice, there are some features are conflict by natural,
  so some test cases may not be picked up. This setting is useful to force run
  perf tests on not designed VM sizes.

Run on Ready computers
----------------------

If you have prepared a Linux computer for testing, please run LISA with
``ready`` runbook:

1. Get the IP address of your computer for testing.

2. Get the SSH public/private key pair which can access this computer.

3. Run LISA with parameters below:

   .. code:: bash

      lisa -r ./microsoft/runbook/ready.yml -v public_address:<public address> -v "user_name:<user name>" -v "admin_private_key_file:<private key file>"

The advantage is it’s not related to any infra. The shortage is that,
some test cases won’t run in Ready platform, for example, test cases
cannot get serial log from a VM directly.

``ready`` runbook also supports tests which require multiple computers (for
example, networking testing); and, it supports password authentication too.
Learn more from :doc:`runbook reference <runbook>`.

For a comprehensive introduction to LISA supported test parameters and runbook
schema, please read :doc:`command-line reference <command_line>` and
:doc:`runbook reference <runbook>`.

Run on Linux and QEMU
---------------------

You can run the tests on Linux machine that has QEMU and KVM installed.

Currently, only the `CBL-Mariner <https://github.com/microsoft/CBL-Mariner>`_ distro
is supported. But it should be fairly straightforward to extend support to other
distros. Also, only the the tier 0 tests are currently supported.

For CBL-Mariner:

1. Acquire a VHDX image of CBL-Mariner.

   For example, you can build your own by following the
   `VHDX and VHD images <https://github.com/microsoft/CBL-Mariner/blob/main/toolkit/docs/quick_start/quickstart.md#vhdx-and-vhd-images>`_
   build instructions.

2. Convert image from VHDX to qcow2:

   .. code:: bash

      qemu-img convert -f vhdx -O qcow2 "<vhdx file>" "<qcow2 file>"

3. Run LISA with the parameters below:

   .. code:: bash

      ./lisa.sh  -r ./microsoft/runbook/qemu/CBL-Mariner.yml -v "admin_private_key_file:<private key file>" -v "qcow2:<qcow2 file>"

Run on AWS
------------

Linux VM can be deployed on AWS using Amazon Machine Image (AMI) that provides
the information required to launch an instance. At current all AWS resources will
be deployed to the same configured region.

1. Configure the credentials for AWS.
   The credentials could be configured in multiple ways. Please create access keys
   for an AWS Identity and Access Management(IAM) user by following the
   `cli configuration quick start <https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html>`_.
   If you have the AWS CLI, then you can run "aws configure" to set up the credentials.

   Or you could add the following configurations to aws runbook:

   .. code:: yaml

      platform:
      - type: aws
         ...
         aws:
            aws_access_key_id: $(aws_access_key_id)
            aws_secret_access_key: $(aws_secret_access_key)
            aws_default_region: $(location)
         requirement:
            ...
            aws:
               ...
               marketplace: "<ami_image_id>"

2. Run LISA with the parameters below:

   .. code:: bash

      ./lisa.sh  -r ./microsoft/runbook/aws.yml -v "admin_username:<username>" -v "admin_private_key_file:<private key file>"

   Update the default user name for the AMI you use to launch the instance.
   For an Ubuntu AMI, the user name is ubuntu. Please refer to the
   `general prerequisites for connecting to the instance <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connection-prereqs.html>`_.
