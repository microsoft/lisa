Run tests on different platforms
================================

-  `Run on Azure <#run-on-azure>`__
-  `Run on Azure without
   deployment <#run-on-azure-without-deployment>`__
-  `Run on Ready computers <#run-on-ready-computers>`__

Run on Azure
------------

VM can be deployed on Azure using images from vhd, shared image
gallery or marketplace. If multiple types are specified, the first
non-empty type is picked in the following order :
vhd, shared image gallery and marketplace.

Running using vhd
^^^^^^^^^^^^^^^^^
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

The `<VHD URL>` can either be a SAS url or a blob url. If it is
a SAS url, the image is copied to the resource group :
`lisa_shared_resource`, storage account :
`lisat{location}{subscription_id[last 8 digits]}` and
container : `lisa-sas-copied` in the subscription used to run LISA,
which could potentially increase the runtime. The copied VHD has
to be manually deleted by the user.

Running using marketplace
^^^^^^^^^^^^^^^^^^^^^^^^^
To run using marketplace image, add the following to runbook :

.. code:: yaml
   platform:
   - type: azure
      ...
      requirement:
         ...
         azure:
            ...
            marketplace: "<Publisher> <Offer> <Sku> <Version>"

Running using shared image gallery
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
To run using shared image gallery, add the following
to runbook if the shared image gallery is in the same
subscription that is used to run LISA :

.. code:: yaml
   platform:
   - type: azure
      ...
      requirement:
         ...
         azure:
            ...
            shared_gallery: "<image_gallery>/<image_definition>/<image_version>"

If the shared image gallery is in a different subscription,
`subscription_id` needs to be specified. Ensure that the
credential used to run LISA has access to the shared image
gallery.

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

Run on Azure without deployment
-------------------------------

In addition to deploying a new Azure server and running tests, you can
skip the deployment phase and use existing resource group.

The advantage is that it can run all test cases of Azure. The shortage
is that the VM name is fixed, and it should be node-0, so each resource
group can put only one VM.

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
