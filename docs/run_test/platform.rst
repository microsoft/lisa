Run tests on different platforms
================================

-  `Run on Azure <#run-on-azure>`__

   *  `Use vhd <#use-vhd>`__
   *  `Use marketplace image <#use-marketplace-image>`__
   *  `Use shared image gallery <#use-shared-image-gallery>`__
   *  `Use existing VMs <#use-existing-vms>`__
   *  `Set other Azure parameters <#set-other-azure-parameters>`__

-  `Run on Ready computers <#run-on-ready-computers>`__

-  `Run on Linux and QEMU <#run-on-linux-and-qemu>`__

-  `Run on AWS <#run-on-aws>`__

-  `Run on WSL <#run-on-wsl>`__

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
            shared_gallery: "<subscription_id>/<resource_group>/<image_gallery>/<image_definition>/<image_version>"

The remaining steps are same as outlined in
:doc:`Getting started with Azure <quick_run>`.

Use existing VMs
^^^^^^^^^^^^^^^^

In addition to deploying a new Azure server and running tests every time, you
can use a deployed resource group or pre-existing resource group. The execution
time is much shorter than deploying a new VM, because it skips deploying VMs,
and avoiding to installing prerequisites packages for some test cases.

If the pre-existing deployment is not created by LISA, the VM names may need to
be specified in the runbook.

1. If there is no deployment to reuse, run with the variables to keep the
   environment after test passed. If there is an existing deployment, skip this
   step.

.. code:: bash

   lisa -r ./microsoft/runbook/azure.yml <other required variables, like subscription id>  -v keep_environment:always

2. Specify the resource group name, and deploy to false to reuse an environment.
   If the environment is deployed by above step, you can find the resource group
   name from the log.

.. code:: bash

   lisa -r ./microsoft/runbook/azure.yml <other required variables, like subscription id> -v deploy:false -v resource_group_name:"<resource group name>"

Set other Azure parameters
^^^^^^^^^^^^^^^^^^^^^^^^^^

The other parameters, like location, vm size, can be specified during
deployment.

.. code:: yaml

   platform:
   - type: azure
      ...
      admin_private_key_file: "<path of private key file>"
      azure:
         virtual_network_resource_group: $(virtual_network_resource_group)
         virtual_network_name: $(virtual_network_name)
         subnet_prefix: $(subnet_prefix)
         use_public_address: "<true or false>"
         create_public_address: "<true or false>"
         use_ipv6: "<true or false>"
         enable_vm_nat: "<true or false>"
         source_address_prefixes: $(source_address_prefixes)
      requirement:
         ...
         ignored_capability:
            - SerialConsole
            - Isolated_Resource
         azure:
            ...
            location: "<one or multiple locations, split by comma>"
            vm_size: "<vm size>"
            maximize_capability: "<true or false>"
            osdisk_size_in_gb: <disk size in gb>

* **admin_private_key_file**: This step is optional. If not provided, LISA will generate a new key pair for you,
  which can be found in the log folder. LISA connects to the Azure test VM via SSH using key authentication. Before running the test, ensure you have a key pair 
  (both public and private keys). If you already have one, you can skip this step. Otherwise, generate a new key pair using the command below:

  .. code:: bash

     ssh-keygen

.. warning::

   Do not use a passphrase to protect your key, as LISA does not support it.
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
* **use_public_address**. True means to connect to the Azure VMs with their 
  public IP addresses.  False means to connect with the private IP addresses.
  If not provided, the connections will default to using the public IP
  addresses.
* **create_public_address**. True means to create a public IP address for the
  Azure VMs. False means not to create a public IP address.  If not provided,
  the connections will default to create a public IP address. It only can be used when use_public_address is set to false.
  When enable_vm_nat is set to true, the VM can access the internet even without a public IP address.
  If enable_vm_nat is set to false, the VM cannot access the internet without a public IP address.
* **use_ipv6**. When use_ipv6 is set to true, LISA uses IPv6 to connect VMs and 
  the platform may enable IPv6 connections during creating VMs. 
  The default value is `false`, it means IPv4 only.
* **enable_vm_nat**. When enable_vm_nat is set to true, the DefaultOutboundAccess 
  property of the subnet will be set to "True". This allows the VMs in the
  subnet to access the internet. The default value is `false`, it means that
  the DefaultOutboundAccess property of the subnet will be set to "False".
  This means that the VMs in the subnet cannot access the internet.
* **source_address_prefixes**. Specify source IP address ranges that are 
  allowed to access the VMs through network security group rules. If not
  provided, your current public IP address will be automatically detected and 
  used. You can specify multiple IP ranges using either comma-separated string
  format or YAML list format. Examples:
  
  .. code:: bash
  
     # Single IP range (string format)
     lisa -r ./microsoft/runbook/azure.yml -v "source_address_prefixes:192.168.1.0/24"
     
     # Multiple IP ranges (comma-separated string format)
     lisa -r ./microsoft/runbook/azure.yml -v "source_address_prefixes:192.168.1.0/24,10.0.0.0/8"
     
     # List format
     lisa -r ./microsoft/runbook/azure.yml -v "source_address_prefixes:['192.168.1.0/24','10.0.0.0/8']"
* **ignored_capability**. Specify feature names which will be ignored in 
  test requirement. You can find the feature name from its name method in source code.
  For example, IsolatedResource feature's name defined in ``lisa/features/isolated_resource.py`` as below:

   .. code:: python

             @classmethod
             def name(cls) -> str:
               return FEATURE_NAME_ISOLATED_RESOURCE

  Then, you can add ``isolated_resource`` to ``ignored_capability``.
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
* **osdisk_size_in_gb** is used to specify the size of the OS disk. If the specified
  size is smaller than the default size, the default size will be used.
  For range of disk size `refer <https://learn.microsoft.com/en-us/azure/virtual-machines/linux/expand-disks?tabs=ubuntu>`__

Run on Ready computers
----------------------

If you have prepared a Linux computer for testing, please run LISA with
``ready`` runbook:

1. Get the IP address of your computer for testing.

2. Get the SSH public/private key pair which can access this computer.

3. Run LISA with parameters below:

   .. code:: bash

      lisa -r ./microsoft/runbook/ready.yml -v public_address:<public address> -v "user_name:<user name>" -v "admin_private_key_file:<private key file>"

The advantage is it's not related to any infra. The shortage is that,
some test cases won't run in Ready platform, for example, test cases
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

Run on WSL
------------

WSL is supported cross all platforms by the guest layer in a node. So, it can be
run with Local, Ready, Azure, AWS, BareMetal, etc. It supports below
functionalities:

* Provisioning WSL from a clean environment, or reuse existing WSL environment.
* Replace the default kernel.
* Install distro by names.
* Support kernel format as tar.xz, unzipped kernel, or a folder which contains a
  file starting with "vmlinux-".

The WSL configurations is under platform section as below.

.. code:: yaml

   platform:
   - type: ready
      guest_enabled: true # Default is false. Make sure set it to true to enable WSL.
      guests:
      - type: wsl
        reinstall: false # Default is false. Set to true to reinstall WSL every time.
        distro: # distro name in Windows store. Default is Ubuntu.
        kernel: # path to replaced kernel
        debug_console: # true or false. Default is false. Set it to true to pop up console for debugging.

If it needs to copy kernel to the Windows host, you can use the
file_uploader transformer to upload the kernel during the "environment_connected"
phase.

.. code:: yaml

   transformer:
   - type: file_uploader
     phase: environment_connected
     source: D:\temp
     destination: \temp
     files:
       - linux-5.15.123.1-microsoft-standard-WSL2.tar.xz
