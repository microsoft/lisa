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
    $vmResource =  Get-ClusterResource | Where-Object {$_.OwnerGroup.name -eq "$vmName" -and $_.ResourceType.Name -eq "Virtual Machine"}
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
    Write-LogInfo "Migrating VM $vmName from $currentNode to $destinationNode"
    $sts = Move-ClusterVirtualMachineRole -name $vmName -node $destinationNode -MigrationType $migrationType
    if (-not $sts) {
        throw "Unable to move the VM"
    }

    if($stopClusterNode) {
        $clusterNodeStopped = $False
        $stoppedNode = Get-ClusterNode -Name $destinationNode
        Write-LogInfo "Stoping cluster service for node ${destinationNode}"
        $null = Stop-ClusterNode -Name $destinationNode
        $stopClusterNode = $False
        Write-LogInfo "Waiting for ${destinationNode}'s cluster service to stop"
        while(-not $clusterNodeStopped) {
            if($stoppedNode.State -eq "Down") {
                $clusterNodeStopped = $True
            }
        }
        Write-LogInfo "Cluster service for node ${destinationNode} is stopped"
        Write-LogInfo "Sleep for 30 sec."
        Start-Sleep -s 30
        Write-LogInfo "Starting cluster service for node ${destinationNode}"
        $null = Start-ClusterNode -Name $destinationNode
        Write-LogInfo "Waiting for ${destinationNode}'s cluster service to be up and running"
        while($clusterNodeStopped) {
            if($stoppedNode.State -eq "Up") {
                $clusterNodeStopped = $False
            }
        }
        Write-LogInfo "${destinationNode}'s cluster service is up and running"
        Write-LogInfo "checking if VM went back to ${currentNode}"
        $vms = Get-VM -ComputerName $currentNode
        foreach($vm in $vms) {
            if($vm.ComputerName.ToLower() -eq $currentNode.ToLower()) {
                Write-LogInfo "Success: ${vmName} went back to ${currentNode}"
                return $True
            }
        }
        throw "VM has not moved back to ${currentNode}"
    }
    Write-LogInfo "Migrating VM $vmName back from $destinationNode to $currentNode"
    $sts= Move-ClusterVirtualMachineRole -name $vmName -node $currentNode -MigrationType $migrationType
    if (-not $sts) {
        throw "$vmName - Unable to move the VM"
    }
    $testResult=$True
}
catch {
    $ErrorMessage =  $_.Exception.Message
    $ErrorLine = $_.InvocationInfo.ScriptLineNumber
    Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
}
Finally {
    if (!$testResult) {
        $testResult = $False
    }
}
return $testResult
