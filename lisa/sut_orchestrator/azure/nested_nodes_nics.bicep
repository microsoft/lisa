param vmName string
param nic_count int
param location string
param vnet_id string
param subnet_prefix string
param existing_subnet_ref string
param enable_sriov bool
param tags object

func getPublicIpAddress(vmName string) object => {
  id: resourceId('Microsoft.Network/publicIPAddresses', '${vmName}-public-ip')
}

var publicIpAddress = getPublicIpAddress(vmName)

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
            id: ((!empty(existing_subnet_ref)) ? existing_subnet_ref : '${vnet_id}/subnets/${subnet_prefix}${i}')
          }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
    enableAcceleratedNetworking: enable_sriov
  }
}]
