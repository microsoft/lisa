param vmName string
param nic_count int
param location string
param vnet_id string
param resource_group_index int
param enable_sriov bool
param tags object
param use_ipv6 bool
param create_public_address bool

func getPublicIpAddress(vmName string, publicIpName string) object => {
  id: resourceId('Microsoft.Network/publicIPAddresses', publicIpName)
}

var publicIpAddress = getPublicIpAddress(vmName, '${vmName}-public-ip')
var publicIpAddressV6 = getPublicIpAddress(vmName, '${vmName}-public-ipv6')

func getSubnetName(resource_group_index int, nic_index int) string => '10.${resource_group_index}.${nic_index}.0'

resource vm_nics 'Microsoft.Network/networkInterfaces@2023-06-01' = [for i in range(0, nic_count): {
  name: '${vmName}-nic-${i}'
  location: location
  tags: tags
  properties: {
    ipConfigurations: concat(
      [
        {
          name: 'IPv4Config'
          properties: {
            privateIPAddressVersion: 'IPv4'
            publicIPAddress: ((0 == i && create_public_address) ? publicIpAddress : null)
            subnet: {
              id: '${vnet_id}/subnets/${getSubnetName(resource_group_index, i)}'
            }
            privateIPAllocationMethod: 'Dynamic'
          }
        }
      ],
      use_ipv6 ? [
        {
          name: 'IPv6Config'
          properties: {
            privateIPAddressVersion: 'IPv6'
            publicIPAddress: ((0 == i && create_public_address) ? publicIpAddressV6 : null)
            subnet: {
              id: '${vnet_id}/subnets/${getSubnetName(resource_group_index, i)}'
            }
            privateIPAllocationMethod: 'Dynamic'
          }
        }
      ] : []
    )
    enableAcceleratedNetworking: enable_sriov
  }
}]
