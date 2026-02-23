param vmName string
param vm_index int
param nic_count int
param location string
param vnet_id string
param subnet_prefix string
param resource_group_index int
param use_existing_vnet bool
param enable_sriov bool
param tags object

func getPublicIpAddress(vmName string) object => {
  id: resourceId('Microsoft.Network/publicIPAddresses', '${vmName}-public-ip')
}

var publicIpAddress = getPublicIpAddress(vmName)

// Shared-VNET mode expects pre-created subnets named as 10.<resource_group_index>.<vm_index>.<nic_index>.
func getSubnetName(resource_group_index int, vm_index int, nic_index int, subnet_prefix string, use_existing_vnet bool) string => use_existing_vnet
? '10.${resource_group_index%256}.${vm_index}.${nic_index}'
: '${subnet_prefix}${nic_index}'

resource vm_nics 'Microsoft.Network/networkInterfaces@2023-06-01' = [for i in range(0, nic_count): {
  name: '${vmName}-nic-${i}'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'IPv4Config'
        properties: {
          privateIPAddressVersion: 'IPv4'
          publicIPAddress: ((0 == i) ? publicIpAddress : null)
          subnet: {
            id: '${vnet_id}/subnets/${getSubnetName(resource_group_index, vm_index, i, subnet_prefix, use_existing_vnet)}'
          }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
    enableAcceleratedNetworking: enable_sriov
  }
}]
