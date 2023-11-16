Transformer References
======================
.. contents:: Index
   :depth: 3


How to
------

Use Shared Image Gallery (SIG) transformer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A Azure Compute Gallery (formerly known as Shared Image Gallery) simplifies custom image sharing across your organization. Custom images are like marketplace images, but you create them yourself. Images can be created from a VM, VHD, snapshot, managed image, or another image version.

Usage
``````
.. code:: yaml

    transformer:
        - type: azure_sig
            vhd: "https://sc.blob.core.windows.net/vhds/pageblob.vhd"
            gallery_resource_group_name: rg_name
            gallery_name: galleryname
            gallery_image_location:
              - westus3
              - westus2
            gallery_image_hyperv_generation: 2
            gallery_image_name: image_name
            gallery_image_architecture: Arm64
            gallery_image_fullname: Microsoft Linux arm64 0.0.1
            rename:
              azure_sig_url: shared_gallery

Process
````````
  - Create Resource group
  - Create Gallery
  - Create Gallery Image
  - Create Gallery Image version


Reference
`````````

vhd (Required)
^^^^^^^^^^^^^^

type: string

raw vhd URL, it can be the blob under the same subscription of SIG or with SASURL


gallery_resource_group_name
^^^^^^^^^^^^^^^^^^^^^^^^^^^

type: string | Default: `shared resource group name`

The name of the resource group that contains the gallery.


gallery_resource_group_location
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

type: string

Default: first location of `gallery image location`

gallery_name (Required)
^^^^^^^^^^^^^^^^^^^^^^^
type: string

The name of the gallery where the image definition and image version will be created.
Gallery will be reused if it exists, otherwise it will be created

gallery_location
^^^^^^^^^^^^^^^^
type: string | Default: first location of `gallery image location`

Location of gallery


gallery_description
^^^^^^^^^^^^^^^^^^^

type: string | Default: ""

Description of gallery

gallery_image_location (Required)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

type: List[str]

The locations where the image definition and image version will be created.


gallery_image_name (Required)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

type: string

Specifies the name of the image. This name must be unique within the gallery and can contain only alphanumeric characters, hyphens, and underscores.
If an existing name is used, the image name is reused.

gallery_image_ostype
^^^^^^^^^^^^^^^^^^^^^^

type: string | Default: "Linux"

Allowed values: "Linux", "Windows"

gallery_image_securitytype
^^^^^^^^^^^^^^^^^^^^^^^^^^

type: string | Default: "" | Allowed values: TrustedLaunch, ""

gallery_image_osstate
^^^^^^^^^^^^^^^^^^^^^

type: string | Default: "Generalized" | Allowed values: "Generalized", "Specialized"


gallery_image_architecture
^^^^^^^^^^^^^^^^^^^^^^^^^^

type: string | Default: "x64" | Allowed values: "x64", "Arm64"

The architecture of the image.

gallery_image_fullname
^^^^^^^^^^^^^^^^^^^^^^

type: string | Default: ""

Full name of image in format: `<publisher> <offer> <sku> <version>`


gallery_image_hyperv_generation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
type: int | Default: 1  | Allowed values: 1, 2

The hyperv generation of the image.

regional_replica_count
^^^^^^^^^^^^^^^^^^^^^^

type: int | Default: 1

Regional replicas are copies of the original image that are stored in different regions, which can improve the performance and availability of the image.

storage_account_type
^^^^^^^^^^^^^^^^^^^^

type: string | Default: Standard_LRS | Allowed Values: Premium_LRS, Standard_ZRS, Standard_LRS


host_caching_type
^^^^^^^^^^^^^^^^^
type: string | Default: "None" | Allowed Values: "None", "ReadOnly", "ReadWrite"


rename
^^^^^^
type: <key>: <value>
Used to rename the output variable

eg: azure_sig_url: shared_gallery
Rename's the transformer output `azure_sig_url` to `shared_gallery`


Use Deploy Transformer
~~~~~~~~~~~~~~~~~~~~~~

Deploy transformer is used to deploy a node in the transformer phase.

Usage
``````
.. code:: yaml

  transformer:
    - type: azure_deploy
      resource_group_name: rg_name
      requirement:
        azure:
          marketplace: image_name
          vhd: vhd_url
          vm_size: Standard_D16ds_v5
          location: westus3
        core_count: 5

Outputs
````````
  - azure_deploy_address
  - azure_deploy_port
  - azure_deploy_username
  - azure_deploy_password
  - azure_deploy_private_key_file

Reference
`````````

resource_group_name
^^^^^^^^^^^^^^^^^^^

type: string 

Name of the resource group in which VM should be deployed. Creates a new RG if not specified.

requirement
^^^^^^^^^^^
type: string

Requirements of the VM such as Image name or VHD. Location to deploy the VM. etc.

core_count
^^^^^^^^^^
type: int

Automatically selects vm_size based on the count provided.


Use Delete Transformer
~~~~~~~~~~~~~~~~~~~~~~

Delete transformer is used to delete an environment.

Usage
``````
.. code:: yaml

  transformer:
    - type: azure_delete
      resource_group_name: rg_name

Reference
`````````

resource_group_name (Required)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

type: string 

Name of the resource group that should be deleted.



Use Vhd Transformer
~~~~~~~~~~~~~~~~~~~

Convert a VM to a VHD using this transformer. This VHD can be used to deploy a VM.

Usage
``````
.. code:: yaml

  transformer:
    - type: azure_vhd
      resource_group_name: rg_name
      vm_name: name_of_vm
      storage_account_name: str = ""
      container_name: container_name
      file_name_part: str = ""
      custom_blob_name: name_of_blob
      restore: false

Outputs
````````
 - azure_vhd_url

Reference
`````````

resource_group_name (Required)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

type: string

Name of the resource group containing the VM.


vm_name
^^^^^^^
type: string

Name of the VM. Required if multiple VMs are present in the resource group.


storage_account_name
^^^^^^^^^^^^^^^^^^^^
type: string | Default: Default LISA storage account 

Name of storage account to save the VHD.

container_name
^^^^^^^^^^^^^^

type: string | Default: "lisa-vhd-exported"

Name of the container in the storage account to export the VHD.

file_name_part
^^^^^^^^^^^^^^^
type: string | Default: ""

Path to use inside the container. Not applicable if `custom_blob_name` is specified.

custom_blob_name
^^^^^^^^^^^^^^^^
type: string | Default: ""

Name of the VHD.

restore
^^^^^^^
type: bool | Default: false

VM is stopped for exporting VHD. Restore can be set to true to start the VM after exporting.
