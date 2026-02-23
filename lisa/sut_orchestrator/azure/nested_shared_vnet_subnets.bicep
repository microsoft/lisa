param virtual_network_name string
param subnet_names array

resource shared_vnet_subnets 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = [for subnet_name in subnet_names: {
  name: '${virtual_network_name}/${subnet_name}'
  properties: {
    addressPrefix: '${subnet_name}/24'
  }
}
]
