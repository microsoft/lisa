// Generic BMI (Bare-Metal Instance) environment template.
//
// Deploys a host group, a jumphost VM with public IP and a secondary internal
// NIC (IP forwarding enabled), and N BMI VMs pinned to dedicated hosts on the
// internal subnet. The internal subnet is route-tabled through the jumphost
// so BMIs egress via SNAT. Per-BMI DNAT rules on the jumphost
// (NAT port -> BMI:22) are configured post-deploy by the BMI platform code,
// not by this template.
//
// Source of truth: this file. Build the deployable artifact with:
//   bicep build bmi.bicep --outfile autogen_bmi_template.json
// The generated JSON is committed alongside this file and loaded at runtime.

@description('Prefix for all resource names within the resource group.')
param namePrefix string

param location string = resourceGroup().location

@minValue(1)
@maxValue(16)
param bmiCount int = 2

param bmiHostSku string = 'GPCv6GB200S186_ETH_metal-Type1'

param jumphostVmSize string = 'Standard_DS2_v2'
param jumphostImagePublisher string = 'Canonical'
param jumphostImageOffer string = '0001-com-ubuntu-server-jammy'
param jumphostImageSku string = '22_04-lts-gen2'
param jumphostImageVersion string = 'latest'
param jumphostUsername string = 'lisatest'

@description('Jumphost admin password. Leave empty to use SSH key authentication via jumphostPublicKey.')
@secure()
param jumphostPassword string = ''

@description('OpenSSH-format public key for jumphost admin user. When non-empty, key-based authentication is enabled.')
param jumphostPublicKey string = ''

param vnetAddressPrefix string = '10.0.0.0/16'
param externalSubnetPrefix string = '10.0.2.0/24'
param internalSubnetPrefix string = '10.0.1.0/24'

@description('Static private IP assigned to the jumphost internal NIC; used as the next-hop for the internal subnet route table. Chosen high in the range to avoid colliding with dynamic IPs Azure allocates to BMI NICs starting at .4.')
param jumphostInternalIp string = '10.0.1.250'

param natPortStart int = 50001

@description('Source IP address prefixes allowed by inbound NSG rules. Defaults to wildcard; set to a list of CIDRs to restrict access.')
param sourceAddressPrefixes array = [
  '*'
]

param bmiVmSize string

param bmiImageId string

// --- Host group settings ---
@minValue(1)
param hostGroupPlatformFaultDomainCount int = 1
param hostGroupSupportAutomaticPlacement bool = true

// --- Jumphost public IP ---
@allowed([
  'Standard'
  'Basic'
])
param publicIpSkuName string = 'Standard'
@allowed([
  'Static'
  'Dynamic'
])
param publicIpAllocationMethod string = 'Static'
@allowed([
  'IPv4'
  'IPv6'
])
param publicIpAddressVersion string = 'IPv4'

// --- Jumphost OS disk ---
@allowed([
  'Premium_LRS'
  'StandardSSD_LRS'
  'Standard_LRS'
])
param jumphostOsDiskStorageAccountType string = 'Premium_LRS'

// --- Jumphost OS profile ---
param jumphostComputerName string = 'jumphost'
param jumphostDisablePasswordAuthentication bool = false

// --- Networking ---
param enableAcceleratedNetworking bool = true

// --- NAT route ---
param natRouteAddressPrefix string = '0.0.0.0/0'
@allowed([
  'VirtualAppliance'
  'VirtualNetworkGateway'
  'VnetLocal'
  'Internet'
  'None'
])
param natRouteNextHopType string = 'VirtualAppliance'

// --- NSG rule priorities ---
@minValue(100)
@maxValue(4096)
param nsgAllowNatPortsPriority int = 200
@minValue(100)
@maxValue(4096)
param nsgJumphostSshPriority int = 202

// --- BMI host ---
@minValue(0)
param bmiHostPlatformFaultDomain int = 0
param bmiHostAutoReplaceOnFailure bool = false

// --- BMI OS disk ---
param bmiOsDiskCreateOption string = 'fromImage'
@allowed([
  'None'
  'ReadOnly'
  'ReadWrite'
])
param bmiOsDiskCaching string = 'ReadOnly'
@allowed([
  'Delete'
  'Detach'
])
param bmiOsDiskDeleteOption string = 'Delete'
param bmiEphemeralDiskOption string = 'Local'
@allowed([
  'CacheDisk'
  'ResourceDisk'
  'NvmeDisk'
])
param bmiEphemeralDiskPlacement string = 'NvmeDisk'

var hostGroupName = '${namePrefix}_hostgroup'
var vnetName = '${namePrefix}_vnet'
var nsgName = '${namePrefix}_nsg'
var routeTableName = '${namePrefix}_nat_routetable'
var jumphostName = '${namePrefix}_jumphost'
var jumphostPublicIpName = '${namePrefix}_jumphostPublicIP'
var jumphostExtNicName = '${namePrefix}_jumphostVMNic'
var jumphostIntNicName = '${namePrefix}_jumphost_internal_nic'
var externalSubnetName = 'external_subnet'
var internalSubnetName = 'internal_subnet'
var natPortEnd = (natPortStart + bmiCount) - 1

resource hostGroup 'Microsoft.Compute/hostGroups@2023-09-01' = {
  name: hostGroupName
  location: location
  properties: {
    platformFaultDomainCount: hostGroupPlatformFaultDomainCount
    supportAutomaticPlacement: hostGroupSupportAutomaticPlacement
  }
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: nsgName
  location: location
  properties: {
    securityRules: [
      {
        name: 'AllowNATPorts'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '${natPortStart}-${natPortEnd}'
          sourceAddressPrefixes: sourceAddressPrefixes
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: nsgAllowNatPortsPriority
          direction: 'Inbound'
        }
      }
      {
        name: 'JumphostSSH'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '22'
          sourceAddressPrefixes: sourceAddressPrefixes
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: nsgJumphostSshPriority
          direction: 'Inbound'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: externalSubnetName
        properties: {
          addressPrefix: externalSubnetPrefix
          networkSecurityGroup: {
            id: nsg.id
          }
        }
      }
      {
        name: internalSubnetName
        properties: {
          addressPrefix: internalSubnetPrefix
          networkSecurityGroup: {
            id: nsg.id
          }
        }
      }
    ]
  }
}

resource jumphostPublicIp 'Microsoft.Network/publicIPAddresses@2023-09-01' = {
  name: jumphostPublicIpName
  location: location
  sku: {
    name: publicIpSkuName
  }
  properties: {
    publicIPAllocationMethod: publicIpAllocationMethod
    publicIPAddressVersion: publicIpAddressVersion
  }
}

resource jumphostExtNic 'Microsoft.Network/networkInterfaces@2023-09-01' = {
  name: jumphostExtNicName
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: {
            id: jumphostPublicIp.id
          }
          subnet: {
            id: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, externalSubnetName)
          }
          primary: true
        }
      }
    ]
    networkSecurityGroup: {
      id: nsg.id
    }
  }
  dependsOn: [
    vnet
  ]
}

resource jumphostIntNic 'Microsoft.Network/networkInterfaces@2023-09-01' = {
  name: jumphostIntNicName
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAddress: jumphostInternalIp
          privateIPAllocationMethod: 'Static'
          subnet: {
            id: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, internalSubnetName)
          }
          primary: true
        }
      }
    ]
    enableAcceleratedNetworking: enableAcceleratedNetworking
    enableIPForwarding: true
    networkSecurityGroup: {
      id: nsg.id
    }
  }
  dependsOn: [
    vnet
  ]
}

resource routeTable 'Microsoft.Network/routeTables@2023-09-01' = {
  name: routeTableName
  location: location
  properties: {
    routes: [
      {
        name: 'NATRoute'
        properties: {
          addressPrefix: natRouteAddressPrefix
          nextHopType: natRouteNextHopType
          nextHopIpAddress: jumphostInternalIp
        }
      }
    ]
  }
}

// Attach the NAT route table to the internal subnet after the vnet exists.
resource internalSubnetWithRoute 'Microsoft.Network/virtualNetworks/subnets@2023-09-01' = {
  name: '${vnetName}/${internalSubnetName}'
  properties: {
    addressPrefix: internalSubnetPrefix
    networkSecurityGroup: {
      id: nsg.id
    }
    routeTable: {
      id: routeTable.id
    }
  }
  dependsOn: [
    vnet
  ]
}

resource jumphostVm 'Microsoft.Compute/virtualMachines@2023-09-01' = {
  name: jumphostName
  location: location
  properties: {
    hardwareProfile: {
      vmSize: jumphostVmSize
    }
    storageProfile: {
      imageReference: {
        publisher: jumphostImagePublisher
        offer: jumphostImageOffer
        sku: jumphostImageSku
        version: jumphostImageVersion
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: jumphostOsDiskStorageAccountType
        }
      }
    }
    osProfile: {
      computerName: jumphostComputerName
      adminUsername: jumphostUsername
      adminPassword: empty(jumphostPassword) ? null : jumphostPassword
      linuxConfiguration: {
        disablePasswordAuthentication: empty(jumphostPassword) ? true : jumphostDisablePasswordAuthentication
        ssh: empty(jumphostPublicKey) ? null : {
          publicKeys: [
            {
              path: '/home/${jumphostUsername}/.ssh/authorized_keys'
              keyData: jumphostPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: jumphostExtNic.id
          properties: {
            primary: true
          }
        }
        {
          id: jumphostIntNic.id
          properties: {
            primary: false
          }
        }
      ]
    }
  }
}

// Dedicated hosts, one per BMI node, all under the same host group.
resource bmiHosts 'Microsoft.Compute/hostGroups/hosts@2023-09-01' = [for i in range(0, bmiCount): {
  parent: hostGroup
  name: '${namePrefix}_bmi_${i + 1}_host'
  location: location
  sku: {
    name: bmiHostSku
  }
  properties: {
    platformFaultDomain: bmiHostPlatformFaultDomain
    autoReplaceOnFailure: bmiHostAutoReplaceOnFailure
  }
}]

// Internal NICs for BMIs.
resource bmiNics 'Microsoft.Network/networkInterfaces@2023-09-01' = [for i in range(0, bmiCount): {
  name: '${namePrefix}_bmi_${i + 1}_internal_nic'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, internalSubnetName)
          }
          primary: true
        }
      }
    ]
    enableAcceleratedNetworking: enableAcceleratedNetworking
    networkSecurityGroup: {
      id: nsg.id
    }
  }
  dependsOn: [
    vnet
  ]
}]

// BMI VMs. Mirrors what `az vm create --specialized --ephemeral-os-disk`
// produces. No `identity` field — the BareMetal Instance RP rejects it.
// Required: VM apiVersion 2024-11-01 (not the SDK default 2021-04-01),
// otherwise Azure Policy injects identity.
resource bmiVms 'Microsoft.Compute/virtualMachines@2024-11-01' = [for i in range(0, bmiCount): {
  name: '${namePrefix}_bmi_${i + 1}'
  location: location
  properties: {
    hardwareProfile: {
      vmSize: bmiVmSize
    }
    host: {
      id: bmiHosts[i].id
    }
    storageProfile: {
      imageReference: {
        id: bmiImageId
      }
      osDisk: {
        createOption: bmiOsDiskCreateOption
        caching: bmiOsDiskCaching
        deleteOption: bmiOsDiskDeleteOption
        diffDiskSettings: {
          option: bmiEphemeralDiskOption
          placement: bmiEphemeralDiskPlacement
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: bmiNics[i].id
          properties: {
            primary: true
          }
        }
      ]
    }
  }
}]

output jumphostPublicIpName string = jumphostPublicIpName
output jumphostName string = jumphostName
output bmiNamePrefix string = '${namePrefix}_bmi_'
output bmiCount int = bmiCount
