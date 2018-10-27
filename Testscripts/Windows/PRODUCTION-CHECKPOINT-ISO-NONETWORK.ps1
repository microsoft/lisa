# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Verify Production Checkpoint feature.

.Description
    This script will stop networking and attach a CD ISO to the vm.
    After that it will proceed with making a Production Checkpoint on test VM
    and check if the ISO is still mounted


.Parameter vmName
    Name of the VM to perform the test with.

.Parameter hvServer
    Name of the Hyper-V server hosting the VM.

.Parameter testParams
    A semicolon separated list of test parameters.
#>

param([string] $testParams)

# Define the guest side script
$NetworkStopScript = "STOR_VSS_StopNetwork.sh"

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
        $url = $TestParams.CDISO
        $captureVMData = $allVMData
        $vmName = $captureVMData.RoleName
        $hvServer= $captureVMData.HyperVhost
        $Ipv4 = $captureVMData.PublicIP
        $VMPort= $captureVMData.SSHPort

        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory

        # if host build number lower than 10500, skip test
        $BuildNumber = Get-HostBuildNumber -hvServer $HvServer
        if ($BuildNumber -eq 0) {
            throw "Incorrect Host Build Number"
        }
        elseif ($BuildNumber -lt 10500) {
            throw "Feature supported only on WS2016 and newer"
        }

        # Check if the Vm VHD in not on the same drive as the backup destination
        $vm = Get-VM -Name $vmName -ComputerName $hvServer

        # Check to see Linux VM is running VSS backup daemon
        $remoteScript="STOR_VSS_Check_VSS_Daemon.sh"
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        LogMsg "VSS Daemon is running"

        #
        # Get Hyper-V VHD path
        #
        $obj = Get-WmiObject -ComputerName $HvServer -Namespace "root\virtualization\v2" -Class "MsVM_VirtualSystemManagementServiceSettingData"
        $defaultVhdPath = $obj.DefaultVirtualHardDiskPath
        if (-not $defaultVhdPath) {
            throw "Unable to determine VhdDefaultPath on Hyper-V server ${hvServer}"
        }
        if (-not $defaultVhdPath.EndsWith("\")) {
            $defaultVhdPath += "\"
        }

        $isoPath = $defaultVhdPath + "${vmName}_CDtest.iso"
        LogMsg "iso path: $isoPath defaultVhdPath $defaultVhdPath"

        $WebClient = New-Object System.Net.WebClient
        $WebClient.DownloadFile("$url", "$isoPath")

        try {
            Get-RemoteFileInfo -filename $isoPath  -server $HvServer
        }
        catch {
            LogErr "The .iso file $isoPath could not be found!"
            throw
        }

        # Insert CD/DVD .
        Set-VMDvdDrive -VMName $vmName -ComputerName $hvServer -Path $isoPath
        if (-not $?) {
            throw "Error: Unable to Add ISO $isoPath"
        }

        LogMsg "Attached DVD: Success"

        # Bring down the network.
        $remoteTest = "echo '${password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${NetworkStopScript} > remotescript.log`""
        LogMsg "Run the remotescript $remoteScript"
        #Run the test on VM
        RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort $remoteTest -runAsSudo

        Start-Sleep -Seconds 3

        # Make sure network is down.
        $sts = ping $ipv4
        $pingresult = $False
        foreach ($line in $sts) {
            if (( $line -Like "*unreachable*" ) -or ($line -Like "*timed*")) {
                $pingresult = $True
            }
        }

        if ($pingresult) {
            LogMsg "Network Down: Success"
        } else {
            throw  "Network Down: Failed"
        }

        #Check if we can set the Production Checkpoint as default
        if ($vm.CheckpointType -ne "ProductionOnly") {
            Set-VM -Name $vmName -CheckpointType ProductionOnly -ComputerName $hvServer
            if (-not $?) {
                throw "Error: Could not set Production as Checkpoint type"
            }
        }

        $random = Get-Random -minimum 1024 -maximum 4096
        $snapshot = "TestSnapshot_$random"
        Checkpoint-VM -Name $vmName -SnapshotName $snapshot -ComputerName $hvServer
        if (-not $?) {
            throw "Error: Could not create checkpoint"
        }

        Restore-VMSnapshot -VMName $vmName -Name $snapshot -ComputerName $hvServer -Confirm:$false
        if (-not $?) {
            throw "Error: Could not restore checkpoint"
        }

        # Starting the VM
        Start-VM $vmName -ComputerName $hvServer

        #
        # Waiting for the VM to run again and respond to SSH - port 22
        #
        $timeout = 300
        $retval = Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout $timeout
        if ($retval -eq $False) {
            throw "Error: Test case timed out waiting for VM to boot"
        }

        # Check if ISO file is still present
        $isoInfo = Get-VMDvdDrive -VMName $vmName -ComputerName $hvServer
        if ($isoInfo.Path -like "*CDTEST*" -eq $False){
            throw "Error: The ISO is missing from the VM"
            $testResult = "FAIL"
        }

        LogMsg "The ISO file is present. Test succeeded"
        $testResult = "PASS"

        #
        # Delete the snapshot
        #
        LogMsg "Deleting Snapshot ${Snapshot} of VM ${vmName}"
        Remove-VMSnapshot -VMName $vmName -Name $snapshot -ComputerName $hvServer
        if ( -not $?) {
            LogErr "Could not delete snapshot"
        }

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

