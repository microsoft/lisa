# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Verify Production Checkpoint feature.
.Description
    This script will check the Production Checkpoint failback feature.
    VSS daemon will be stopped inside the VM and Hyper-V should be able
    to create a standard checkpoint in this case.
    The test will pass if a Standard Checkpoint will be made in this case.
#>
function Main {
    $currentTestResult = CreateTestResultObject
    $resultArr = @()
    try{
        $testResult = $null

        $captureVMData = $allVMData
        $VMName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4 = $captureVMData.PublicIP
        $VMPort= $captureVMData.SSHPort

        # Change the working directory to where we need to be
        Set-Location $WorkingDirectory
        LogMsg "Check host version and skip TC in case of older than WS2016"
        $BuildNumber =  Get-HostBuildNumber $HvServer
        if ($BuildNumber -eq 0) {
            throw "Invalid Windows build number"
        }
        elseif ($BuildNumber -lt 10500) {
	        LogMsg "Info: Feature supported only on WS2016 and newer"
        }

        # Check to see Linux VM is running VSS backup daemon
        $remoteScript="STOR_VSS_Check_VSS_Daemon.sh"
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        LogMsg "VSS Daemon is running"

        # Stop the VSS daemon gracefully
        $remoteScript="PC_Stop_VSS_Daemon.sh"
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }
        LogMsg "VSS Daemon was successfully stopped"

        $vm = Get-VM -Name $VMName -ComputerName $HvServer
        # Check if we can set the Production Checkpoint as default
        if ($vm.CheckpointType -ne "ProductionOnly") {
            Set-VM -Name $VMName -ComputerName $HvServer -CheckpointType Production
        }

        $random = Get-Random -minimum 1024 -maximum 4096
        $snapshot = "TestSnapshot_$random"

        LogMsg "Info : creating Checkpoint ${snapshot} of VM ${VMName}"
        Checkpoint-VM -Name $VMName -SnapshotName $snapshot -ComputerName $HvServer
        if (-not $?) {
            LogErr "Could not create Standard checkpoint with $snapshot"
            $testResult = $resultFail
        }
        else {
            LogMsg "Standard Checkpoint successfully created"
        }

        LogMsg "Info : Deleting Snapshot ${snapshot} of VM ${VMName}"
        Remove-VMSnapshot -VMName $VMName -Name $snapshot -ComputerName $HvServer

        if( $testResult -ne $resultFail) {
            LogMsg "Info : Only the first file is present. Test succeeded"
            $testResult=$resultPass
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
Main
