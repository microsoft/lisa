@description('Name of the existing remote virtual network to peer with')
param remoteVnetName string

@description('ID of the local VNet')
param localVnetId string

@description('resource group index (for unique naming)')
param resource_group_index int

resource remoteVnet 'Microsoft.Network/virtualNetworks@2023-11-01' existing = {
  name: remoteVnetName
}

resource peering 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2023-11-01' = {
        parent: remoteVnet
        name: 'vnet-peering-e${resource_group_index}'
        properties: {
          allowVirtualNetworkAccess: true
          localSubnetNames: [ 'default' ]
          peerCompleteVnets: false
          remoteSubnetNames:['default']
          remoteVirtualNetwork: {
            id: localVnetId
          }
          //remoteVirtualNetwork: orchestrator_vnet // reference to the orchestrator vnet
        }
  }
