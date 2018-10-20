# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Verify Production Checkpoint feature.

.Description
    This script will create a new VM with a 3-chained differencing disk
    attached based on the source vm vhd/x.
    If the source Vm has more than 1 snapshot, they will be removed except
    the latest one. If the VM has no snapshots, the script will create one.
    After that it will proceed with making a Production Checkpoint on the
    new VM.
.Parameter vmName
    Name of the VM to perform the test with.

.Parameter hvServer
    Name of the Hyper-V server hosting the VM.

.Parameter testParams
    A semicolon separated list of test parameters.

#>

param([string] $testParams)

#######################################################################
# Fix snapshots. If there are more than one, remove all except latest.
#######################################################################
function FixSnapshots($vmName, $hvServer)
{
    # Get all the snapshots
    $vmsnapshots = Get-VMSnapshot -VMName $vmName
    $snapnumber = ${vmsnapshots}.count

    # Get latest snapshot
    $latestsnapshot = Get-VMSnapshot -VMName $vmName | Sort-Object CreationTime | Select-Object -Last 1
    $LastestSnapName = $latestsnapshot.name

    # Delete all snapshots except the latest
    if ($snapnumber -gt 1) {
        LogMsg "$vmName has $snapnumber snapshots. Removing all except $LastestSnapName"
        foreach ($snap in $vmsnapshots) {
            if ($snap.id -ne $latestsnapshot.id) {
                $snapName = ${snap}.Name
                $sts = Remove-VMSnapshot -Name $snap.Name -VMName $vmName -ComputerName $hvServer
                if (-not $?) {
                    LogErr "ERROR: Unable to remove snapshot $snapName of ${vmName}: `n${sts}"
                    return $False
                }
                LogMsg "Removed snapshot $snapName"
            }
        }
    }

    # If there are no snapshots, create one.
    ElseIf ($snapnumber -eq 0) {
        LogMsg "There are no snapshots for $vmName. Creating one ..."
        $sts = Checkpoint-VM -VMName $vmName -ComputerName $hvServer
        if (-not $?) {
           LogErr "ERROR: Unable to create snapshot of ${vmName}: `n${sts}"
           return $False
        }
    }

    return $True
}

#######################################################################
# To Create Grand Child VHD from Parent VHD.
#######################################################################
function CreateGChildVHD($ParentVHD)
{
    $GChildVHD = $null
    $ChildVHD  = $null

    $hostInfo = Get-VMHost -ComputerName $hvServer
    if (-not $hostInfo) {
             LogErr "Error: Unable to collect Hyper-V settings for ${hvServer}"
             return $False
        }

    $defaultVhdPath = $hostInfo.VirtualHardDiskPath
        if (-not $defaultVhdPath.EndsWith("\")) {
            $defaultVhdPath += "\"
        }

    # Create Child VHD
    if ($ParentVHD.EndsWith("x") ) {
        $ChildVHD = $defaultVhdPath+$vmName+"-child.vhdx"
        $GChildVHD = $defaultVhdPath+$vmName+"-Gchild.vhdx"
    }
    else {
        $ChildVHD = $defaultVhdPath+$vmName+"-child.vhd"
        $GChildVHD = $defaultVhdPath+$vmName+"-Gchild.vhd"
    }

    if ( Test-Path  $ChildVHD ) {
        LogMsg "Deleting existing VHD $ChildVHD"
        Remove-Item $ChildVHD
    }

    if ( Test-Path  $GChildVHD ) {
        LogMsg "Deleting existing VHD $GChildVHD"
        Remove-Item $GChildVHD
    }

    # Create Child VHD
    New-VHD -ParentPath:$ParentVHD -Path:$ChildVHD
    if (-not $?) {
       LogErr "Error: Unable to create child VHD"
       return $False
    }

    # Create Grand Child VHD
    New-VHD -ParentPath:$ChildVHD -Path:$GChildVHD
    if (-not $?) {
       LogErr "Error: Unable to create Grand child VHD"
       return $False
    }

    return $GChildVHD
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
    try{
        $testResult = $null
        $captureVMData = $allVMData
        $vmName = $captureVMData.RoleName
        $hvServer= $captureVMData.HyperVhost
        $ipv4 = $captureVMData.PublicIP
        $port= $captureVMData.SSHPort

        $vmNameChild = "${vmName}_ChildVM"

        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        # if host build number lower than 10500, skip test
        $BuildNumber = Get-HostBuildNumber $hvServer
        if ($BuildNumber -eq 0) {
            throw "Incorrect Host Build Number"
        }
        elseif ($BuildNumber -lt 10500) {
            throw "Feature supported only on WS2016 and newer"
        }

        # Check if the Vm VHD in not on the same drive as the backup destination
        $vm = Get-VM -Name $vmName -ComputerName $hvServer
        if (-not $vm) {
            throw "VM '${vmName}' does not exist"
        }

        # Check to see Linux VM is running VSS backup daemon
        $remoteScript="STOR_VSS_Check_VSS_Daemon.sh"
        $stateFile = "${LogDir}\state.txt"
        $Hypervcheck = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > Hypervcheck.log`""
        RunLinuxCmd -username $user -password $password -ip $ipv4 -port $port $Hypervcheck -runAsSudo
        RemoteCopy -download -downloadFrom $ipv4 -files "/home/${user}/state.txt" `
            -downloadTo $LogDir -port $port -username $user -password $password
        RemoteCopy -download -downloadFrom $ipv4 -files "/home/${user}/Hypervcheck.log" `
            -downloadTo $LogDir -port $port -username $user -password $password
        $contents = Get-Content -Path $stateFile
        if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
            throw "Running $remoteScript script failed on VM!"
        }

        LogMsg "VSS Daemon is running"

        # Stop the running VM so we can create New VM from this parent disk.
        Stop-VM -ComputerName $hvServer -Name $vmName -Force -Confirm:$false
        if (-not $?) {
               throw "Unable to Shut Down VM"
        }

        # Add Check to make sure if the VM is shutdown then Proceed
        $timeout = 180
        $sts = Wait-ForVMToStop $vmName $hvServer $timeout
        if (-not $sts) {
            throw "WaitForVMToStop fail"
        }

        # Clean snapshots
        LogMsg "Cleaning up snapshots..."
        $sts = FixSnapshots $vmName $hvServer
        if (-not $sts[-1]) {
            throw "Error: Cleaning snapshots on $vmname failed."
        }

        # Get Parent VHD
        $ParentVHD = Get-ParentVHD $vmName $hvServer
        if(-not $ParentVHD) {
            throw "Error getting Parent VHD of VM $vmName"
        }

        LogMsg "Successfully Got Parent VHD"

        # Create Child and Grand Child VHD
        $CreateVHD = CreateGChildVHD $ParentVHD
        if(-not $CreateVHD) {
            throw  "Error Creating Child and Grand Child VHD of VM $vmName"
        }

        LogMsg "Successfully Created GrandChild VHD"

        # Now create New VM out of this VHD.
        # New VM is static hardcoded since we do not need it to be dynamic
        $GChildVHD = $CreateVHD[-1]

        # Get-VM
        $vm = Get-VM -Name $vmName -ComputerName $hvServer

        # Get the VM Network adapter so we can attach it to the new vm.
        $VMNetAdapter = Get-VMNetworkAdapter $vmName
        if (-not $?) {
            throw  "Get-VMNetworkAdapter Failed"
        }

        # Get VM Generation
        $vm_gen = $vm.Generation

        # Create the GChildVM
        New-VM -Name $vmNameChild -VHDPath $GChildVHD -MemoryStartupBytes 1024MB -SwitchName $VMNetAdapter[0].SwitchName -Generation $vm_gen
        if (-not $?) {
            throw "Failure in Creating New VM"
        }

        # Disable secure boot
        if ($vm_gen -eq 2) {
            Set-VMFirmware -VMName $vmNameChild -EnableSecureBoot Off -ComputerName $hvServer
            if(-not $?) {
                throw "Unable to disable secure boot"
            }
        }

        LogMsg "New 3 Chain VHD VM $vmNameChild Created"

        $timeout = 500
        $sts = Start-VM -Name $vmNameChild -ComputerName $hvServer
        if (-not (Wait-ForVMToStartKVP $vmNameChild $hvServer $timeout )) {
            throw "${vmNameChild} failed to start"
        }

        LogMsg "New VM $vmNameChild started"

        #Check if we can set the Production Checkpoint as default
        $vmChild = Get-VM -Name $vmNameChild -ComputerName $hvServer
        if ($vmChild.CheckpointType -ne "ProductionOnly") {
            Set-VM -Name $vmNameChild -CheckpointType ProductionOnly -ComputerName $hvServer
            if (-not $?) {
                throw "Could not set Production as Checkpoint type"
            }
        }

        LogMsg "Get the new IPv4 for $vmNameChild"
        # Get new IPV4
        $newIP = Get-IPv4AndWaitForSSHStart -VMName $vmNameChild -HvServer $hvServer `
                -VmPort $port -User $user -Password $password -StepTimeout 360
        if ($newIP) {
            $vm2ipv4 = $newIP
        } else {
            throw "Failed to boot up NFS Server $vm2Name"
        }

        LogMsg "IPv4 $newIP for $vmNameChild"

        $cmd = "echo y | exit"
        RunLinuxCmd -username $user -password $password -ip $vm2ipv4 -port $port -command $cmd -runAsSudo

        # Create a file on the child VM
        RunLinuxCmd -username $user -password $password -ip $vm2ipv4 -port $port -command "touch TestFile1" -runAsSudo
        if (-not $?) {
             throw "Cannot create file TestFile1"
        }

        # Take a Production Checkpoint
        $random = Get-Random -minimum 1024 -maximum 4096
        $snapshot = "TestSnapshot_$random"
        Checkpoint-VM -Name $vmNameChild -SnapshotName $snapshot -ComputerName $hvServer
        if (-not $?) {
            throw "Could not create checkpoint"
        }

        # Create another file on the VM
        RunLinuxCmd -username $user -password $password -ip $vm2ipv4 -port $port -command "touch TestFile2" -runAsSudo
        if (-not $?) {
             throw "Cannot create file TestFile2"
        }

        Restore-VMSnapshot -VMName $vmNameChild -Name $snapshot -ComputerName $hvServer -Confirm:$false
        if (-not $?) {
            throw "Could not restore checkpoint"
        }

        #
        # Starting the child VM
        #
        $sts = Start-VM -Name $vmNameChild -ComputerName $hvServer
        if (-not (Wait-ForVMToStartKVP $vmNameChild $hvServer $timeout )) {
            throw  "${vmNameChild} failed to start"
        }

        LogMSg "New VM ${vmNameChild} started"

        # Check the files created earlier. The first one should be present, the second one shouldn't
        $sts1 = Check-FileInLinuxGuest -VMPassword $password -VMPort $port -VMUserName $user -Ipv4 $vm2ipv4 -fileName "TestFile1"
        if (-not $sts1) {
            $testResult = $resultFail
            throw "TestFile1 is not present, it should be present on the VM"
        }

        $sts2 = Check-FileInLinuxGuest -VMPassword $password -VMPort $port -VMUserName $user -Ipv4 $vm2ipv4 -fileName "TestFile2"
        if ($sts2) {
            $testResult = $resultFail
            throw "TestFile2 is present,it should not be present on the VM"
        }

        LogMsg "Only the first file is present. Test succeeded"
        #
        # Delete the snapshot
        #
        LogMsg "Deleting Snapshot ${Snapshot} of VM ${vmName}"
        Remove-VMSnapshot -VMName $vmNameChild -Name $snapshot -ComputerName $hvServer
        if ( -not $?) {
            throw "Could not delete snapshot"
        }

        # Stop child VM
        Stop-VM -ComputerName $hvServer -Name $vmNameChild -Force -Confirm:$false
        if (-not $?) {
               throw "Unable to Shut Down VM"
        }

        # Add Check to make sure if the VM is shutdown then Proceed
        $timeout = 180
        $sts = Wait-ForVMToStop $vmNameChild $hvServer $timeout
        if (-not $sts) {
                throw "WaitForVMToStop fail"
        }

        # Clean Delete New VM created
        $sts = Remove-VM -Name $vmNameChild -Confirm:$false -Force
        if (-not $?) {
            throw "Deleting New VM $vmNameChild"
        }

        LogMSg "Deleted VM $vmNameChild"
        $testResult = "PASS"
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -TestParams  (ConvertFrom-StringData $TestParams.Replace(";","`n"))
