Transformer References
======================
.. contents:: Index
   :depth: 3


How to
------


Outputs of transformer
~~~~~~~~~~~~~~~~~~~~~~

Some transformers generate output variables that can be referenced in other transformers or processes. The output variable names follow these rules:

- If ``prefix`` is specified, all output variables use it, and neither ``name`` nor ``type`` will take effect.
- If ``prefix`` is not specified but ``name`` is, the output variables use ``name``.
- If neither ``prefix`` nor ``name`` is specified, the output variables use ``type``.

Usage
`````

If only ``type`` is provided (no ``name`` or ``prefix``):

.. code-block:: yaml

   transformer:
     - type: azure_deploy

The output variables will be:

- ``azure_deploy_address``
- ``azure_deploy_port``
- ``azure_deploy_username``
- ``azure_deploy_password``
- ``azure_deploy_private_key_file``

If ``name`` is provided but ``prefix`` is not:

.. code-block:: yaml

   transformer:
     - type: azure_deploy
       name: custom_name

The output variables will be:

- ``custom_name_address``
- ``custom_name_port``
- ``custom_name_username``
- ``custom_name_password``
- ``custom_name_private_key_file``

If ``prefix`` is provided (regardless of whether ``name`` is set):

.. code-block:: yaml

   transformer:
     - type: azure_deploy
       name: custom_name
       prefix: my_prefix

The output variables will be:

- ``my_prefix_address``
- ``my_prefix_port``
- ``my_prefix_username``
- ``my_prefix_password``
- ``my_prefix_private_key_file``

Since ``prefix`` is set, the values of ``name`` and ``type`` will not affect the output variable names.


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
      deploy: true
      source_address_prefixes: 
        - "192.168.1.0/24"
        - "10.0.0.0/8"
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

Name of the resource group in which VM should be deployed. Creates a new RG if not specified. When not provided, the platform configuration will be used for the transformer. When the VM of transformer has different resource group requirements, it can be overwritten here. This only works for new fresh deployment - if the resource group already exists, it does nothing.

requirement
^^^^^^^^^^^
type: string

Requirements of the VM such as Image name or VHD. Location to deploy the VM. etc.

core_count
^^^^^^^^^^
type: int

Automatically selects vm_size based on the count provided.

deploy
^^^^^^
type: bool | Default: true

Whether to create a new deployment. If true, creates a new VM deployment. If false, uses existing VMs in the specified resource_group_name.

source_address_prefixes
^^^^^^^^^^^^^^^^^^^^^^^
type: Optional[Union[str, List[str]]] | Default: None

Source address prefixes for network security rules. Can be a single string, a comma-separated string, or a list of strings. When not specified, defaults to the current public IP address for security. When not provided, the platform configuration will be used for the transformer. When the VM of transformer has different network infrastructure requirements, it can be overwritten here.


Use Delete Transformer
~~~~~~~~~~~~~~~~~~~~~~

Delete transformer is used to delete an environment.

Usage
``````
.. code:: yaml

  transformer:
    - type: azure_delete
      resource_group_name: rg_name
      keep_environment: "failed"
      wait_delete: true

Reference
`````````

resource_group_name (Required)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

type: string 

Name of the resource group that should be deleted.

keep_environment
^^^^^^^^^^^^^^^

type: string | bool | Default: "no"

Whether to keep the environment after deletion. Allowed values: "always", "no", "failed", or True/False.

wait_delete
^^^^^^^^^^

type: bool | Default: false

Whether to wait for the deletion to complete. If set to true, the transformer will wait for the resource group to be fully deleted before proceeding.


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


Use Script File Transformer
~~~~~~~~~~~~~~~~~~~~~~~~~~

This transformer is used to install required packages, execute scripts on a node, and optionally reboot the node after execution.

Usage
``````
.. code:: yaml

  transformer:
    - type: script_file
      phase: expanded
      connection:
        address: $(build_vm_address)
        private_key_file: $(admin_private_key_file)
      reboot: true
      dependent_packages:
        - git
      scripts:
        - script: "/tmp/waagent.sh"
          interpreter: bash
          args: "--flag"
          expected_exit_code: 0

Outputs
````````
 - results

Reference
`````````

dependent_packages
^^^^^^^^^^^^^^^^^
type: List[str] | Default: []

List of packages to install before executing scripts.

scripts (Required)
^^^^^^^^^^^^^^^
type: List[ScriptEntry]

List of scripts to execute on the node.

Script Entry Properties:

script (Required)
""""""""""""""""
type: string

Path to the script file on the target node.

interpreter
""""""""""
type: string | Default: "bash"

Interpreter to use for executing the script. Currently only bash is supported.

args
""""
type: string | Default: None

Arguments to pass to the script.

expected_exit_code
""""""""""""""""
type: int | Default: 0

Expected exit code of the script. If the script returns a different exit code, execution will fail.

reboot
^^^^^
type: bool | Default: false

Reboot the node after script execution.
