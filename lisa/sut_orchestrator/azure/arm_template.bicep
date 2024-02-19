@description('storage name for boot diagnosis')
param storage_name string

@description('storage name for copied vhds')
param vhd_storage_name string

@description('location')
param location string

@description('all nodes')
param nodes array

@description('user name')
param admin_username string

@description('password')
param admin_password string

@description('public key data')
param admin_key_data string

@description('the name of shared resource group')
param shared_resource_group_name string

@description('created subnet count')
param subnet_count int

@description('options for availability sets, zones, and VMSS')
param availability_options object

@description('the name of vnet resource group')
param virtual_network_resource_group string

@description('the name of vnet')
param virtual_network_name string

@description('the prefix of the subnets')
param subnet_prefix string

@description('tags of virtual machine')
param vm_tags object

@description('data disk array.')
param data_disks array

@description('whether to use ultra disk')
param is_ultradisk bool = false

var vnet_id = virtual_network_name_resource.id
var node_count = length(nodes)
var availability_set_name_value = 'lisa-availabilitySet'
var existing_subnet_ref = (empty(virtual_network_resource_group) ? '' : resourceId('Microsoft.Network/virtualNetworks/subnets', virtual_network_resource_group, virtual_network_name, subnet_prefix))
var availability_set_tags = availability_options.availability_set_tags
var availability_set_properties = availability_options.availability_set_properties
var availability_zones = availability_options.availability_zones
var availability_type = availability_options.availability_type
var use_availability_set = (availability_type == 'availability_set')
var use_availability_zones = (availability_type == 'availability_zone')
var availability_set_value = (use_availability_set ? getAvailabilitySetId(availability_set_name_value): null)

func getOSDisk(diskName string) object => {
  createOption: 'Attach'
  osType: 'Linux'
  managedDisk: { id: resourceId('Microsoft.Compute/disks', diskName) }
}

func getOsDiskVhd(vmName string) object => {
  id: resourceId('Microsoft.Compute/images', '${vmName}-image')
}

func getLinuxConfiguration(keyPath string, publicKeyData string, disable_password_authentication bool) object => {
  disablePasswordAuthentication: disable_password_authentication
  ssh: {
      publicKeys: [
          {
              path: keyPath
              keyData: publicKeyData
          }
      ]
  }
  provisionVMAgent: true
}

func getEphemeralOSImage(node object) object => {
  name: '${node.name}-osDisk'
  diffDiskSettings: {
      option: 'local'
      placement: 'CacheDisk'
  }
  caching: 'ReadOnly'
  createOption: 'FromImage'
  diskSizeGB: node.osdisk_size_in_gb
}

func getCreateDisk(disk object, diskName string, index int) object => {
  name: diskName
  createOption: disk.create_option
  caching: disk.caching_type
  diskSizeGB: disk.size
  lun: index
  managedDisk: {
      storageAccountType: disk.type
  }
}

func getAttachDisk(disk object, diskName string, index int) object => {
  lun: index
  createOption: 'attach'
  caching: disk.caching_type
  managedDisk: {
      id: resourceId('Microsoft.Compute/disks', diskName)
  }
}

func getOsDiskSharedGallery(node object) object => {
  id: resourceId(node.subscription_id, empty(node.resource_group_name) ? 'None' : node.resource_group_name, 'Microsoft.Compute/galleries/images/versions', node.image_gallery, node.image_definition, node.image_version)
}

func getOsDiskMarketplace(node object) object => {
  publisher: node.marketplace.publisher
  offer: node.marketplace.offer
  sku: node.marketplace.sku
  version: node.marketplace.version
}

func getSecurityProfileForOSDisk(node object) object => empty(node.security_profile.disk_encryption_set_id)
? {
  securityEncryptionType: node.security_profile.encryption_type
} : {
  securityEncryptionType: node.security_profile.encryption_type
  diskEncryptionSet: {
    id: node.security_profile.disk_encryption_set_id
  }
}

func generateOsProfile(node object, admin_username string, admin_password string, admin_key_data string) object => {
  computername: node.short_name
  adminUsername: admin_username
  adminPassword: (empty(admin_password) ? null : admin_password)
  linuxConfiguration: (((!empty(admin_key_data)) && node.is_linux) ? getLinuxConfiguration('/home/${admin_username}/.ssh/authorized_keys', admin_key_data, empty(admin_password)) : null)
}

func generateImageReference(node object) object => (isVhd(node) ? getOsDiskVhd(node.name)
: ((!empty(node.shared_gallery))
? getOsDiskSharedGallery(node.shared_gallery)
: getOsDiskMarketplace(node)))

func generateSecurityProfile(node object) object => {
  uefiSettings: {
    secureBootEnabled: node.security_profile.secure_boot
    vTpmEnabled: true
  }
  securityType: node.security_profile.security_type
}

func getOsProfile(node object, admin_username string, admin_password string, admin_key_data string) object => isCvm(node) 
? {}
: generateOsProfile(node, admin_username, admin_password, admin_key_data)

func getImageReference(node object) object => isCvm(node) 
? {}
: generateImageReference(node)

func getSecurityProfile(node object) object => empty(node.security_profile) 
? {} 
: generateSecurityProfile(node)

func getOSImage(node object) object => {
  name: '${node.name}-osDisk'
  managedDisk: {
    storageAccountType: node.os_disk_type
    securityProfile: (empty(node.security_profile) || (node.security_profile.security_type != 'ConfidentialVM')) ? null : getSecurityProfileForOSDisk(node)
  }
  caching: ((node.os_disk_type == 'Ephemeral') ? 'ReadOnly' : 'ReadWrite')
  createOption: 'FromImage'
  diskSizeGB: node.osdisk_size_in_gb
}

func getAvailabilitySetId(availability_set_name string) object => {
  id: resourceId('Microsoft.Compute/availabilitySets', availability_set_name)
}

func isCvm(node object) bool => bool((!empty(node.vhd)) && (!empty(node.vhd.vmgs_path)))

func isVhd(node object) bool => bool((!empty(node.vhd)) && (!empty(node.vhd.vhd_path)))

func getVMOsDisk(node object) object => isCvm(node) ? getOSDisk('${node.name}-disk')
: ((node.os_disk_type == 'Ephemeral')
? getEphemeralOSImage(node)
: getOSImage(node))

func getDataDisk(nodeName string, dataDisk object, index int) object => (dataDisk.type == 'UltraSSD_LRS')
? getAttachDisk(dataDisk, '${nodeName}-data-disk-${index}', index)
: getAttachDisk(dataDisk, '${nodeName}-data-disk-${index}', index)

module nodes_nics './nested_nodes_nics.bicep' = [for i in range(0, node_count): {
  name: '${nodes[i].name}-nics'
  params: {
    vmName: nodes[i].name
    nic_count: nodes[i].nic_count
    location: location
    vnet_id: vnet_id
    subnet_prefix: subnet_prefix
    existing_subnet_ref: existing_subnet_ref
    enable_sriov: nodes[i].enable_sriov
  }
}]

resource virtual_network_name_resource 'Microsoft.Network/virtualNetworks@2020-05-01' = if (empty(virtual_network_resource_group)) {
  name: virtual_network_name
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.0.0.0/16'
      ]
    }
    subnets: [for j in range(0, subnet_count): {
      name: '${subnet_prefix}${j}'
      properties: {
        addressPrefix: '10.0.${j}.0/24'
      }
    }]
  }
}

resource availability_set 'Microsoft.Compute/availabilitySets@2019-07-01' = if (use_availability_set) {
  name: availability_set_name_value
  location: location
  tags: availability_set_tags
  sku: {
    name: 'Aligned'
  }
  properties: availability_set_properties
}

resource nodes_public_ip 'Microsoft.Network/publicIPAddresses@2020-05-01' = [for i in range(0, node_count): {
  location: location
  name: '${nodes[i].name}-public-ip'
  properties: {
    publicIPAllocationMethod: (is_ultradisk ? 'Static' : 'Dynamic')
  }
  sku: {
    name: (is_ultradisk ? 'Standard' : 'Basic')
  }
  zones: (use_availability_zones ? availability_zones : null)
}]

resource nodes_image 'Microsoft.Compute/images@2019-03-01' = [for i in range(0, node_count): if (isVhd(nodes[i]) && empty(nodes[i].vhd.vmgs_path)) {
  name: '${nodes[i].name}-image'
  location: location
  properties: {
    storageProfile: {
      osDisk: {
        osType: 'Linux'
        osState: 'Generalized'
        blobUri: nodes[i].vhd.vhd_path
        storageAccountType: 'Standard_LRS'
      }
    }
    hyperVGeneration: 'V${nodes[i].hyperv_generation}'
  }
}]

resource nodes_disk 'Microsoft.Compute/disks@2021-04-01' = [for i in range(0, node_count): if (isCvm(nodes[i])) {
  name: '${nodes[i].name}-disk'
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    osType: 'Linux'
    hyperVGeneration: 'V${nodes[i].hyperv_generation}'
    securityProfile: {
      securityType: 'ConfidentialVM_VMGuestStateOnlyEncryptedWithPlatformKey'
    }
    creationData: {
      createOption: 'ImportSecure'
      storageAccountId: resourceId(shared_resource_group_name, 'Microsoft.Storage/storageAccounts', vhd_storage_name)
      securityDataUri: nodes[i].vhd.vmgs_path
      sourceUri: nodes[i].vhd.vhd_path
    }
  }
  zones: (use_availability_zones ? availability_zones : null)
}]

resource nodes_data_disks 'Microsoft.Compute/disks@2022-03-02' = [
  for i in range(0, (length(data_disks) * node_count)): {
    name: '${nodes[(i / length(data_disks))].name}-data-disk-${(i % length(data_disks))}'
    location: location
    properties: {
      diskSizeGB: data_disks[(i % length(data_disks))].size
      creationData: {
        createOption: data_disks[(i % length(data_disks))].create_option
      }
      diskIOPSReadWrite: data_disks[(i % length(data_disks))].iops
      diskMBpsReadWrite: data_disks[(i % length(data_disks))].throughput
    }
    sku: {
      name: data_disks[(i % length(data_disks))].type
    }
    zones: (use_availability_zones ? availability_zones : null)
  }
]

resource nodes_vms 'Microsoft.Compute/virtualMachines@2022-08-01' = [for i in range(0, node_count): {
  name: nodes[i].name
  location: nodes[i].location
  tags: vm_tags
  plan: nodes[i].purchase_plan
  properties: {
    availabilitySet: availability_set_value
    hardwareProfile: {
      vmSize: nodes[i].vm_size
    }
    osProfile: getOsProfile(nodes[i], admin_username, admin_password, admin_key_data)
    storageProfile: {
      imageReference: getImageReference(nodes[i])
      osDisk:  getVMOsDisk(nodes[i])
      diskControllerType: (nodes[i].disk_controller_type == 'SCSI') ? null : nodes[i].disk_controller_type
      dataDisks: [for (item, j) in data_disks: getDataDisk(nodes[i].name, item, j)]
    }
    networkProfile: {
      networkInterfaces: [for j in range(0, nodes[i].nic_count): {
        id: resourceId('Microsoft.Network/networkInterfaces', '${nodes[i].name}-nic-${j}')
        properties: {
          primary: ((j == 0) ? true : false)
        }
      }]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
        storageUri: reference(resourceId(shared_resource_group_name, 'Microsoft.Storage/storageAccounts', storage_name), '2015-06-15').primaryEndpoints.blob
      }
    }
    additionalCapabilities: {
      ultraSSDEnabled: (nodes[i].data_disk_type == 'UltraSSD_LRS') ? true: false
    }
    securityProfile: getSecurityProfile(nodes[i])
  }
  zones: (use_availability_zones ? availability_zones : null)
  dependsOn: [
    availability_set
    nodes_image
    nodes_nics
    virtual_network_name_resource
    nodes_disk
    nodes_data_disks
  ]
}]
