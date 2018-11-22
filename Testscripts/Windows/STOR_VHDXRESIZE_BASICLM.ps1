# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Verify basic VHDx Hard Disk resizing.
.Description
    This is a PowerShell test case script that implements Dynamic
    Resizing of VHDX after migration
    Ensures that the VM sees the newly attached VHDx Hard Disk
    Creates partitions, filesytem, mounts partitions, sees if it can perform
    Read/Write operations on the newly created partitions and deletes partitions
#>
param(
    [String] $TestParams
)
$ErrorActionPreference = "Stop"
function Move-VMClusterNode([String] $vmName)
{
    #
    # Load the cluster commandlet module
    #
    Import-module FailoverClusters
    if (-not $?) {
        LogErr "Unable to load FailoverClusters module"
        return $False
    }
    #
    # Have migration networks been configured?
    #
    $migrationNetworks = Get-ClusterNetwork
    if (-not $migrationNetworks) {
        LogErr "$vmName - There are no Live Migration Networks configured"
        return $False
    }
    LogMsg "Get the VMs current node"
    $vmResource =  Get-ClusterResource | where-object {$_.OwnerGroup.name -eq "$vmName" -and $_.ResourceType.Name -eq "Virtual Machine"}
    if (-not $vmResource) {
        LogErr "$vmName - Unable to find cluster resource for current node"
        return $False
    }
    $currentNode = $vmResource.OwnerNode.Name
    if (-not $currentNode) {
        LogErr "$vmName - Unable to set currentNode"
        return $False
    }
    #
    # Get nodes the VM can be migrated to
    #
    $clusterNodes = Get-ClusterNode
    if (-not $clusterNodes -and $clusterNodes -isnot [array]) {
        LogErr "$vmName - There is only one cluster node in the cluster."
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
        LogErr "$vmName - Unable to set destination node"
        return $False
    }
    LogMsg "Migrating VM $vmName from $currentNode to $destinationNode"
    $sts = Move-ClusterVirtualMachineRole -name $vmName -node $destinationNode
    if (-not $sts) {
        LogErr "$vmName - Unable to move the VM"
        return $False
    }
    return $True
}

#######################################################################
#
# Main script body
#
#######################################################################
function Main {
    param (
        $TestParams
    )
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4 = $captureVMData.PublicIP
        $VMPort= $captureVMData.SSHPort
        $NewSize=$TestParams.NewSize
        if ($TestParams.Contains("IDE")) {
            $controllerType = "IDE"
            $vmGeneration = Get-VMGeneration $VMName $HvServer
            if ($vmGeneration -eq 2 ) {
                throw "Generation 2 VM does not support IDE disk, skip test"
            }
        }
        elseif ($TestParams.Contains("SCSI")) {
            $controllerType = "SCSI"
        }
        else {
            throw "Could not determine ControllerType"
        }
        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        #
        # Verify if the VM is clustered
        #
        Get-Command "Get-ClusterResource" -ErrorAction SilentlyContinue
        if ($?) {
            $cluster_vm = Get-ClusterGroup -Name $VMName -ErrorAction SilentlyContinue
            if (-not $cluster_vm) {
                throw "Test skipped: VM $VMName is not running on a cluster."
            }
        }
        #
        # Convert the new size
        #
        $newVhdxSize =  Convert-StringToUInt64 $NewSize
        #
        # Make sure the VM has a SCSI 1 controller, and that
        # Lun 1 on the controller has a .vhdx file attached.
        #
        LogMsg "Check if VM ${VMName} has a SCSI 1 Lun 1 drive"
        $vhdxName = $VMName + "-" + $controllerType
        $vhdxDisks = Get-VMHardDiskDrive -VMName $VMName -ComputerName $HvServer
        foreach ($vhdx in $vhdxDisks) {
            $vhdxPath = $vhdx.Path
            if ($vhdxPath.Contains($vhdxName)) {
                $vhdxDrive = Get-VMHardDiskDrive -VMName $VMName -Controllertype SCSI -ControllerNumber $vhdx.ControllerNumber `
                 -ControllerLocation $vhdx.ControllerLocation -ComputerName $HvServer -ErrorAction SilentlyContinue
            }
        }
        if (-not $vhdxDrive) {
            throw "VM ${VMName} does not have a SCSI 0 Lun 0 drive"
        }
        LogMsg "Check if the virtual disk file exists"
        $vhdPath = $vhdxDrive.Path
        $vhdxInfo = Get-RemoteFileInfo $vhdPath $HvServer
        if (-not $vhdxInfo) {
            $testResult = "FAIL"
            throw "The vhdx file (${vhdPath} does not exist on server ${HvServer}"
        }
        LogMsg "Verify the file is a .vhdx"
        if (-not $vhdPath.EndsWith(".vhdx") -and -not $vhdPath.EndsWith(".avhdx")) {
            $testResult = "FAIL"
            throw "$controllerType $vhdxDrive.ControllerNumber $vhdxDrive.ControllerLocation virtual disk is not a .vhdx file."
        }
        # Make sure there is sufficient disk space to grow the VHDX to the specified size
        $deviceID = $vhdxInfo.Drive
        $diskInfo = Get-CimInstance -Query "SELECT * FROM Win32_LogicalDisk Where DeviceID = '${deviceID}'" -ComputerName $HvServer
        if (-not $diskInfo) {
            throw "Unable to collect information on drive ${deviceID}"
        }
        if ($diskInfo.FreeSpace -le $newVhdxSize + 10MB) {
            throw "Insufficent disk free space, This test case requires ${testParameters.NewSize} free, Current free space is $($diskInfo.FreeSpace)"
        }
        RunLinuxCmd -ip $Ipv4 -port $VMPort -username $user -password $password -command "echo 'deviceName=/dev/sdc' >> constants.sh" -runAsSudo
        $remoteScript="STOR_VHDXResize_PartitionDisk.sh"
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $Password $Ipv4 $VMPort
        #$retval=RunLinuxCmd -ip $Ipv4 -port $VMPort -username $user -password $password -command "./$remoteScript" -runAsSudo
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        LogMsg "Resizing the VHDX to $newVhdxSize"
        Resize-VHD -Path $vhdPath -SizeBytes ($newVhdxSize) -ComputerName $HvServer -ErrorAction SilentlyContinue
        if (-not $?) {
            throw "Unable to grow VHDX file ${vhdPath}"
        }
        #
        # Check if the guest sees the added space
        #
        LogMsg "Check if the guest sees the new space"
        RunLinuxCmd -ip $Ipv4 -port $VMPort -username $user -password $password -command "echo 1 > /sys/block/sdc/device/rescan" -runAsSudo
        $diskSize = RunLinuxCmd -ip $Ipv4 -port $VMPort -username $user -password $password -command "fdisk -l /dev/sdc  2> /dev/null | grep Disk | grep sdc | cut -f 5 -d ' '" -runAsSudo
        #
        # Let system have some time for the volume change to be indicated
        #
        Start-Sleep -S 30
        if ($diskSize -ne $newVhdxSize) {
            throw "VM ${VMName} sees a disk size of ${diskSize}, not the expected size of ${newVhdxSize}"
        }
        #
        # Make sure if we can perform Read/Write operations on the guest VM
        #
        RunLinuxCmd -ip $Ipv4 -port $VMPort -username $user -password $password -command "sed -i '/rerun=yes/d' constants.sh" -runAsSudo
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        # Migrate the VM to another host
        $migrateResult= Move-VMClusterNode $VMName
        if (-not $migrateResult) {
            $testResult = $resultFail
            throw "Migration failed"
        }
        #
        # Make sure if we can perform Read/Write operations on the guest VM
        #
        RunLinuxCmd -ip $Ipv4 -port $VMPort -username $user -password $password -command "sed -i '/rerun=yes/d' constants.sh" -runAsSudo
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        #
        # Migrate the VM back to original host
        #
        $migrateResult= Move-VMClusterNode $VMName
        if (-not $migrateResult) {
            $testResult = $resultFail
            throw "Migration failed"
        }
        if( $testResult -ne $resultFail) {
            $testResult=$resultPass
        }
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "$ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
