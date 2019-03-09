# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests Secure Boot features.
.Description
    This script will test Secure Boot features on a Generation 2 VM.
    It also test the feature after performing a Live Migration of the VM or
    after a kernel update.
#>
param([string] $TestParams, [object] $AllVMData)
$ErrorActionPreference = "Stop"
function Enable-VMMigration([String] $vmName)
{
    #
    # Load the cluster commandlet module
    #
    Import-module FailoverClusters
    if (-not $?) {
        Write-LogErr "Unable to load FailoverClusters module"
        return $False
    }
    #
    # Have migration networks been configured?
    #
    $migrationNetworks = Get-ClusterNetwork
    if (-not $migrationNetworks) {
        Write-LogErr "$vmName - There are no Live Migration Networks configured"
        return $False
    }
    Write-LogInfo "Get the VMs current node"
    $vmResource =  Get-ClusterResource | Where-Object {$_.OwnerGroup.name -eq "$vmName" -and $_.ResourceType.Name -eq "Virtual Machine"}
    if (-not $vmResource) {
        Write-LogErr "$vmName - Unable to find cluster resource for current node"
        return $False
    }
    $currentNode = $vmResource.OwnerNode.Name
    if (-not $currentNode) {
        Write-LogErr "$vmName - Unable to set currentNode"
        return $False
    }
    #
    # Get nodes the VM can be migrated to
    #
    $clusterNodes = Get-ClusterNode
    if (-not $clusterNodes -and $clusterNodes -isnot [array]) {
        Write-LogErr "$vmName - There is only one cluster node in the cluster."
        return $False
    }
    #
    # For the initial implementation, just pick a node that does not
    # match the current VMs node
    #
    $destinationNode = $clusterNodes[0].Name.ToLower()
    if ($currentNode -eq $clusterNodes[0].Name.ToLower()) {
        $destinationNode = $clusterNodes[1].Name.ToLower()
    }
    if (-not $destinationNode) {
        Write-LogErr "$vmName - Unable to set destination node"
        return $False
    }
    Write-LogInfo "Migrating VM $vmName from $currentNode to $destinationNode"
    $sts = Move-ClusterVirtualMachineRole -name $vmName -node $destinationNode
    if (-not $sts) {
        Write-LogErr "$vmName - Unable to move the VM"
        return $False
    }
    #
    # Check if Secure Boot is enabled
    #
    $firmwareSettings = Get-VMFirmware -VMName $vmName -ComputerName $destinationNode
    if ($firmwareSettings.SecureBoot -ne "On") {
        Write-LogErr "Secure boot settings changed"
        return $False
    }
    $sts = Move-ClusterVirtualMachineRole -name $vmName -node $currentNode
    if (-not $sts) {
        Write-LogErr "$vmName - Unable to move the VM"
        return $False
    }
    return $True
}
##########################################################################
#
# Main script body
#
##########################################################################
function Main {
    param (
        $TestParams, $AllVMData
    )
    $currentTestResult = Create-TestResultObject
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4 = $captureVMData.PublicIP
        $VMPort= $captureVMData.SSHPort
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        #
        # Check heartbeat
        #
        $heartbeat = Get-VMIntegrationService -VMName $VMName -Name "HeartBeat"
        if ($heartbeat.Enabled) {
            Write-LogInfo "$VMName heartbeat detected"
        }
        else {
            throw "$VMName heartbeat not detected"
        }
        #
        # Waiting for the VM to run again and respond to SSH - port 22
        #
        $timeout = 500
        while ($timeout -gt 0) {
            if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
                break
            }
            Start-Sleep -seconds 2
            $timeout -= 2
        }
        if ($timeout -eq 0) {
            throw "Test case timed out waiting for VM to boot"
        }
        Write-LogInfo "SSH port opened"
        if ($TestParams.Migrate) {
            $migrateResult= Enable-VMMigration $VMName
            if (-not $migrateResult) {
                $testResult = $resultFail
                throw "Migration failed"
            }
            #
            # Check if Secure boot settings are in place after migration
            #
            $firmwareSettings = Get-VMFirmware -VMName $VMName
            if ($firmwareSettings.SecureBoot -ne "On") {
                $testResult = $resultFail
                throw "Secure boot settings changed"
            }
            #
            # Waiting for the VM to run again and respond to SSH - port 22
            #
            $timeout = 500
            while ($timeout -gt 0) {
                if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
                    break
                }
                Start-Sleep -seconds 2
                $timeout -= 2
            }
            if ($timeout -eq 0) {
                throw "Test case timed out waiting for VM to boot"
            }
            Write-LogInfo "SSH port opened"

        }
        if ($TestParams.updateKernel) {
            # Getting kernel version before upgrade
            $kernel_beforeupgrade = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "uname -a" -runAsSudo
            # Upgrading kernel to latest
            $Upgradecheck = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;. utils.sh && UtilsInit && Update_Kernel`""
            $null = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $Upgradecheck -runAsSudo
            Write-LogInfo "Shutdown VM ${VMName}"
            Stop-VM -ComputerName $HvServer -Name $VMName -Confirm:$false
            if (-not $?) {
                throw "Unable to Shut Down VM"
            }
            $timeout = 180
            $sts = Wait-ForVMToStop $VMName $HvServer $timeout
            if (-not $sts) {
                throw "Wait-ForVMToStop fail"
            }
            Write-LogInfo "Starting VM ${VMName}"
            Start-VM -Name $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
            if (-not $?) {
                throw "unable to start the VM"
            }
            $sleepPeriod = 5 # seconds
            Start-Sleep -s $sleepPeriod
            #
            # Check heartbeat
            #
            $heartbeat = Get-VMIntegrationService -VMName $VMName -Name "HeartBeat"
            if ($heartbeat.Enabled) {
                Write-LogInfo "$VMName heartbeat detected"
            }
            else {
                throw "$VMName heartbeat not detected"
            }
            #
            # Waiting for the VM to run again and respond to SSH - port 22
            #
            $timeout = 500
            $retval = Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout $timeout
            if ($retval -eq $False) {
                throw "Error: Test case timed out waiting for VM to boot"
            }
            Write-LogInfo "SSH port opened"
            # Getting kernel version after upgrade
            $kernel_afterupgrade = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command "uname -a" -runAsSudo
            # check whether kernel has upgraded to latest version
            if (-not (Compare-Object $kernel_afterupgrade $kernel_beforeupgrade)) {
                $testResult = $resultFail
                throw "Update_Kernel failed"
            }
            Write-LogInfo "Success: Updated kerenl"
        }
        if( $testResult -ne $resultFail) {
            $testResult=$resultPass
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -AllVMData $AllVMData
