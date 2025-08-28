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

@description('tags of azure resources')
param tags object

@description('data disk array.')
param data_disks array

@description('whether to use ultra disk')
param is_ultradisk bool = false

@description('IP Service Tags')
param ip_service_tags object

@description('whether to use ipv6')
param use_ipv6 bool = false

@description('whether to enable network outbound access')
param enable_vm_nat bool

@description('The source IP address prefixes allowed in NSG')
param source_address_prefixes array

@description('Generate public IP address for each node')
param create_public_address bool

var vmContributorRoleDefinitionId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
var managedIdentityResourceGroup = 'gsatestresourcegroup'
var managedIdentitySubscriptionId = 'e7eb2257-46e4-4826-94df-153853fea38f'
var managedIdentityName = 'gsateststorage-blobreader'
var managedIdentityResourceId = resourceId(
  managedIdentitySubscriptionId,
  managedIdentityResourceGroup,                        
  'Microsoft.ManagedIdentity/userAssignedIdentities',
  managedIdentityName
)
var vnet_id = virtual_network_name_resource.id
var node_count = length(nodes)
var availability_set_name_value = 'lisa-availabilitySet'
var existing_subnet_ref = (empty(virtual_network_resource_group) ? '' : resourceId(virtual_network_resource_group, 'Microsoft.Network/virtualNetworks/subnets', virtual_network_name, subnet_prefix))
var availability_set_tags = availability_options.availability_set_tags
var availability_set_properties = availability_options.availability_set_properties
var availability_zones = availability_options.availability_zones
var availability_type = availability_options.availability_type
var use_availability_set = (availability_type == 'availability_set')
var use_availability_zones = (availability_type == 'availability_zone')
var availability_set_value = (use_availability_set ? getAvailabilitySetId(availability_set_name_value): null)
var combined_vm_tags = union(tags, vm_tags)
var combined_aset_tags = union(tags, availability_set_tags)
var ip_tags = [for key in objectKeys(ip_service_tags): {
  ipTagType: key
  tag: ip_service_tags[key]
}]

func isCvm(node object) bool => bool((!empty(node.vhd)) && (!empty(node.vhd.vmgs_path)))

func isVhd(node object) bool => bool((!empty(node.vhd)) && (!empty(node.vhd.vhd_path)))

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
      placement: node.ephemeral_disk_placement_type
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

func getDataDisk(nodeName string, dataDisk object, index int) object => (dataDisk.type == 'UltraSSD_LRS')
? getAttachDisk(dataDisk, '${nodeName}-data-disk-${index}', index)
: getCreateDisk(dataDisk, '${nodeName}-data-disk-${index}', index)

func getOsDiskSharedGallery(shared_gallery object) object => {
  id: resourceId(shared_gallery.subscription_id, empty(shared_gallery.resource_group_name) ? 'None' : shared_gallery.resource_group_name, 'Microsoft.Compute/galleries/images/versions', shared_gallery.image_gallery, shared_gallery.image_definition, shared_gallery.image_version)
}

func getOSDiskCommunityGalleryImage(community_gallery_image object) object => {
  communityGalleryImageId: '/CommunityGalleries/${community_gallery_image.image_gallery}/Images/${community_gallery_image.image_definition}/Versions/${community_gallery_image.image_version}'
}

func getOsDiskMarketplace(marketplace object) object => {
  publisher: marketplace.publisher
  offer: marketplace.offer
  sku: marketplace.sku
  version: marketplace.version
}

func generateImageReference(node object) object => isVhd(node)
? getOsDiskVhd(node.name)
: !empty(node.shared_gallery)
? getOsDiskSharedGallery(node.shared_gallery)
: !empty(node.community_gallery_image)
? getOSDiskCommunityGalleryImage(node.community_gallery_image)
: getOsDiskMarketplace(node.marketplace)

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

func generateSecurityProfile(node object) object => {
  uefiSettings: {
    secureBootEnabled: node.security_profile.secure_boot
    vTpmEnabled: true
  }
  securityType: node.security_profile.security_type
}

func getOsProfile(node object, admin_username string, admin_password string, admin_key_data string) object? => isCvm(node) 
? null
: generateOsProfile(node, admin_username, admin_password, admin_key_data)

func getImageReference(node object) object? => isCvm(node) 
? null
: generateImageReference(node)

func getSecurityProfile(node object) object? => empty(node.security_profile) 
? null
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

func getVMOsDisk(node object) object => isCvm(node) ? getOSDisk('${node.name}-disk')
: ((node.os_disk_type == 'Ephemeral')
? getEphemeralOSImage(node)
: getOSImage(node))

func getAvailabilitySetId(availability_set_name string) object => {
  id: resourceId('Microsoft.Compute/availabilitySets', availability_set_name)
}

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
    tags: tags
    use_ipv6: use_ipv6
    create_public_address: create_public_address
  }
  dependsOn: [
    nodes_public_ip[i]
    nodes_public_ip_ipv6[i]
  ]
}]

resource virtual_network_name_resource 'Microsoft.Network/virtualNetworks@2024-05-01' = if (empty(virtual_network_resource_group)) {
  name: virtual_network_name
  tags: tags
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: concat(
        ['10.0.0.0/16'],
        use_ipv6 ? ['2001:db8::/32'] : []
      )
    }
    subnets: [for j in range(0, subnet_count): {
      name: '${subnet_prefix}${j}'
      properties: {
        addressPrefixes: concat(
          ['10.0.${j}.0/24'],
          use_ipv6 ? ['2001:db8:${j}::/64'] : []
        )
        defaultOutboundAccess: enable_vm_nat
        networkSecurityGroup: {
          id: resourceId('Microsoft.Network/networkSecurityGroups', '${toLower(virtual_network_name)}-nsg')
        }
      }
    }]
  }
  dependsOn: [
    nsg
  ]
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${toLower(virtual_network_name)}-nsg'
  location: location
  properties: {
    securityRules: [
      {
        name: 'LISASSH'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '22'
          sourceAddressPrefixes: source_address_prefixes
          destinationAddressPrefix: '*'
        }
      }
      {
          name: 'LISAKVMSSH'
          properties: {
              description: 'Allows nested VM SSH traffic'
              protocol: 'Tcp'
              sourcePortRange: '*'
              destinationPortRange: '60020-60030'
              destinationAddressPrefix: '*'
              sourceAddressPrefixes: source_address_prefixes
              access: 'Allow'
              priority: 206
              direction: 'Inbound'
          }
      }
      {
        name: 'LISALIBVIRTSSH'
        properties: {
            description: 'Allows SSH traffic to Libvirt Platform Guests'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '49152-49352'
            destinationAddressPrefix: '*'
            sourceAddressPrefixes: source_address_prefixes
            access: 'Allow'
            priority: 208
            direction: 'Inbound'
        }
      }
    ]
  }
}

resource availability_set 'Microsoft.Compute/availabilitySets@2019-07-01' = if (use_availability_set) {
  name: availability_set_name_value
  location: location
  tags: combined_aset_tags
  sku: {
    name: 'Aligned'
  }
  properties: availability_set_properties
}

resource nodes_public_ip 'Microsoft.Network/publicIPAddresses@2020-05-01' = [for i in range(0, node_count): if (create_public_address) {
  location: location
  tags: tags
  name: '${nodes[i].name}-public-ip'
  properties: {
    publicIPAllocationMethod: 'Static'
    ipTags: (empty(ip_tags) ? null : ip_tags)
  }
  sku: {
    name: 'Standard'
  }
  zones: (use_availability_zones ? availability_zones : null)
}]

resource nodes_public_ip_ipv6 'Microsoft.Network/publicIPAddresses@2020-05-01' = [for i in range(0, node_count): if (use_ipv6 && create_public_address) {
  name: '${nodes[i].name}-public-ipv6'
  location: location
  tags: tags
  properties: {
    publicIPAllocationMethod: 'Static'
    ipTags: (empty(ip_tags) ? null : ip_tags)
    publicIPAddressVersion: 'IPv6'
  }
  sku: {
    name: 'Standard'
  }
  zones: (use_availability_zones ? availability_zones : null)
}]

resource nodes_image 'Microsoft.Compute/images@2019-03-01' = [for i in range(0, node_count): if (isVhd(nodes[i]) && empty(nodes[i].vhd.vmgs_path)) {
  name: '${nodes[i].name}-image'
  tags: tags
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
  tags: tags
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
  /*
    Create ultra data disks with setting iops and throughput, and attach them to the VMs.
    There is no way to use getCreateDisk with setting iops and throughput.
  */
  for i in range(0, (length(data_disks) * node_count)): if (is_ultradisk) {
    name: '${nodes[(i / length(data_disks))].name}-data-disk-${(i % length(data_disks))}'
    location: location
    tags: tags
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

resource nodes_vms 'Microsoft.Compute/virtualMachines@2024-03-01' = [for i in range(0, node_count): {
  name: nodes[i].name
  location: nodes[i].location
  tags: combined_vm_tags
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
  ]
}]


resource msi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  scope: resourceGroup(managedIdentitySubscriptionId, managedIdentityResourceGroup)
  name: managedIdentityName
}


resource vmContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = [for i in range(0, node_count): {
  name: guid(nodes[i].name, 'vm-contributor-role')
  scope: nodes_vms[i]
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', vmContributorRoleDefinitionId)
    principalId: msi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}]