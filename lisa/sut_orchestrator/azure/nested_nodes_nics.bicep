param vmName string
param nic_count int
param location string
param vnet_id string
param subnet_prefix string
param existing_subnet_ref string
param enable_sriov bool
param tags object
param use_ipv6 bool
param use_ipv6_public bool = false
param use_ipv6_internal bool = false
param create_public_address bool

func getPublicIpAddress(vmName string, publicIpName string) object => {
  id: resourceId('Microsoft.Network/publicIPAddresses', publicIpName)
}

var publicIpAddress = getPublicIpAddress(vmName, '${vmName}-public-ip')
var publicIpAddressV6 = getPublicIpAddress(vmName, '${vmName}-public-ipv6')

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
              id: ((!empty(existing_subnet_ref)) ? existing_subnet_ref : '${vnet_id}/subnets/${subnet_prefix}${i}')
            }
            privateIPAllocationMethod: 'Dynamic'
          }
        }
      ],
      (use_ipv6 || use_ipv6_internal) ? [
        {
          name: 'IPv6Config'
          properties: {
            privateIPAddressVersion: 'IPv6'
            publicIPAddress: ((0 == i && create_public_address && (use_ipv6 || use_ipv6_public)) ? publicIpAddressV6 : null)
            subnet: {
              id: ((!empty(existing_subnet_ref)) ? existing_subnet_ref : '${vnet_id}/subnets/${subnet_prefix}${i}')
            }
            privateIPAllocationMethod: 'Dynamic'
          }
        }
      ] : []
    )
    enableAcceleratedNetworking: enable_sriov
  }
}]
