# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Performs basic Live/Quick Migration operations
.Description
    This is a Powershell script that migrates a VM from one cluster node
    to another.
    The script assumes that the second node is configured
#>

param([string] $vmName, [string] $hvServer, [string] $migrationType, [string] $stopClusterNode, [string] $VMMemory, [string] $WorkingDirectory)
$testResult = $null
try {
    # Load Module CommonFunctions.psm1
    Import-Module $WorkingDirectory\Libraries\CommonFunctions.psm1
    #
    # Load the cluster cmdlet module
    #
    $sts = Get-Module | Select-String -Pattern FailoverClusters -Quiet
    if (! $sts) {
        Import-Module FailoverClusters
    }
    #
    # Check if migration networks are configured
    #
    $migrationNetworks = Get-ClusterNetwork
    if (-not $migrationNetworks) {
        throw "There are no migration networks configured"
    }
    #
    # Get the VMs current node
    #
    $vmResource =  Get-ClusterResource | where-object {$_.OwnerGroup.name -eq "$vmName" -and $_.ResourceType.Name -eq "Virtual Machine"}
    if (-not $vmResource) {
        throw "Unable to find cluster resource for current node"
    }
    $currentNode = $vmResource.OwnerNode.Name
    if (-not $currentNode) {
        throw "Unable to set currentNode"
    }
    #
    # Get nodes the VM can be migrated to
    #
    $clusterNodes = Get-ClusterNode
    if (-not $clusterNodes -and $clusterNodes -isnot [array]) {
        throw "There is only one cluster node in the cluster."
    }
    # Picking up a node that does not match the current VMs node
    $destinationNode = $clusterNodes[0].Name.ToLower()
    if ($currentNode -eq $clusterNodes[0].Name.ToLower()) {
        $destinationNode = $clusterNodes[1].Name.ToLower()
    }
    if (-not $destinationNode) {
        throw "Unable to set destination node"
    }
    # Check resources on destination node
    if ($VMMemory) {
        $startupMemory = Convert-StringToDecimal $VMMemory
        $availableMemory = [string](Get-Counter -Counter "\Memory\Available MBytes" -ComputerName $destinationNode).CounterSamples[0].CookedValue + "MB"
        $availableMemory = Convert-StringToDecimal $availableMemory
        if ($startupMemory -gt $availableMemory) {
            throw "Not enough available memory on the destination node. startupMemory: $startupMemory, free space: $availableMemory"
        }
    }
    LogMsg "Migrating VM $vmName from $currentNode to $destinationNode"
    $sts = Move-ClusterVirtualMachineRole -name $vmName -node $destinationNode -MigrationType $migrationType
    if (-not $sts) {
        throw "Unable to move the VM"
    }

    if($stopClusterNode) {
        $clusterNodeStopped = $False
        $stoppedNode = Get-ClusterNode -Name $destinationNode
        LogMsg "Stoping cluster service for node ${destinationNode}"
        Stop-ClusterNode -Name $destinationNode
        $stopClusterNode = $False
        LogMsg "Waiting for ${destinationNode}'s cluster service to stop"
        while(-not $clusterNodeStopped) {
            if($stoppedNode.State -eq "Down") {
                $clusterNodeStopped = $True
            }
        }
        LogMsg "Cluster service for node ${destinationNode} is stopped"
        LogMsg "Sleep for 30 sec."
        Start-Sleep -s 30
        LogMsg "Starting cluster service for node ${destinationNode}"
        Start-ClusterNode -Name $destinationNode
        LogMsg "Waiting for ${destinationNode}'s cluster service to be up and running"
        while($clusterNodeStopped) {
            if($stoppedNode.State -eq "Up") {
                $clusterNodeStopped = $False
            }
        }
        LogMsg "${destinationNode}'s cluster service is up and running"
        LogMsg "checking if VM went back to ${currentNode}"
        $vms = Get-VM -ComputerName $currentNode
        foreach($vm in $vms) {
            if($vm.ComputerName.ToLower() -eq $currentNode.ToLower()) {
                LogMsg "Success: ${vmName} went back to ${currentNode}"
                return $True
            }
        }
        throw "VM has not moved back to ${currentNode}"
    }
    LogMsg "Migrating VM $vmName back from $destinationNode to $currentNode"
    $sts= Move-ClusterVirtualMachineRole -name $vmName -node $currentNode -MigrationType $migrationType
    if (-not $sts) {
        throw "$vmName - Unable to move the VM"
    }
    $testResult=$True
}
catch {
    $ErrorMessage =  $_.Exception.Message
    $ErrorLine = $_.InvocationInfo.ScriptLineNumber
    LogMsg "EXCEPTION : $ErrorMessage at line: $ErrorLine"
}
Finally {
    if (!$testResult) {
        $testResult = $False
    }
}
return $testResult
