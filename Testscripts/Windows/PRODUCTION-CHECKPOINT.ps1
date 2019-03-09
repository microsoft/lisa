# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Verify Production Checkpoint feature.

.Description
    Tests to see if the virtual machine Production Checkpoint operation
    works as expected. Steps:
     - Create a file on VM
     - Take a Production Checkpoint
     - Create a second file on VM
     - Revert to the Production Checkpoint
     - Boot the VM, only the first file should exist
#>
param([object] $AllVmData)

$ErrorActionPreference = "Stop"

function Main {
    $currentTestResult = Create-TestResultObject
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
        Write-LogInfo "Check host version and skip TC in case of older than WS2016"
        $BuildNumber =  Get-HostBuildNumber $HvServer
        if ($BuildNumber -eq 0) {
            throw "Invalid Windows build number"
        }
        elseif ($BuildNumber -lt 10500) {
	        Write-LogInfo "Feature supported only on WS2016 and newer"
        }
        # Check if the VM VHD in not on the same drive as the backup destination
        $vm = Get-VM -Name $VMName -ComputerName $HvServer

        # Check to see Linux VM is running VSS backup daemon
        $remoteScript="STOR_VSS_Check_VSS_Daemon.sh"
        $retval = Invoke-RemoteScriptAndCheckStateFile $remoteScript $user $password $Ipv4 $VMPort
        if ($retval -eq $False) {
            throw "Running $remoteScript script failed on VM!"
        }

        Write-LogInfo "VSS Daemon is running"

        # Create a file on the VM
        $testfile1="Testfile_$(Get-Random -minimum 1 -maximum 1000)"
        Write-LogInfo "Creating ${testfile1}"
        New-Item -type file -name $testfile1 -force | Out-Null
        Copy-RemoteFiles -upload -uploadTo $Ipv4 -Port $VMPort `
                    -files $testfile1 -Username $user -password $password
        #Check if we can set the Production Checkpoint as default
        if ($vm.CheckpointType -ne "ProductionOnly"){
            Set-VM -Name $VMName -ComputerName $HvServer -CheckpointType ProductionOnly
        }

        $random = Get-Random -minimum 1024 -maximum 4096
        $snapshot = "TestSnapshot_$random"

        Write-LogInfo "creating Production Checkpoint ${snapshot} of VM ${VMName}"
        Checkpoint-VM -Name $VMName -SnapshotName $snapshot -ComputerName $HvServer
        if (-not $?) {
            throw "Could not create Production checkpoint with $snapshot"
        }

        # Create another file on the VM
        $testfile2="Testfile_$(Get-Random -minimum 1 -maximum 1000)"
        Write-LogInfo "Creating ${testfile2}"
        New-Item -type file -name $testfile2 -force | Out-Null
        Copy-RemoteFiles -upload -uploadTo $Ipv4 -Port $VMPort `
                    -files $testfile2 -Username $user -password $password
        Write-LogInfo "Restoring Production Checkpoint ${snapshot}"
        Restore-VMSnapshot -VMName $VMName -Name $snapshot -ComputerName $HvServer -Confirm:$false

        #
        # Starting the VM
        #
        Start-VM $VMName -ComputerName $HvServer

        #
        # Waiting for the VM to run again and respond to SSH - port 22
        #
        $timeout = 500
        $retval = Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout $timeout
        if ($retval -eq $False) {
            throw "Error: Test case timed out waiting for VM to boot"
        }

        $sts = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName $testfile1
        if (-not $sts) {
            Write-LogErr "${testfile1} is not present, it should be present on the VM"
            $testResult = $resultFail

        }

        $sts = Check-FileInLinuxGuest -VMPassword $password -VMPort $VMPort -VMUserName $user -Ipv4 $Ipv4 -fileName $testfile2
        if ($sts) {
            Write-LogErr "${testfile2} is present,it should not be present on the VM"
            $testResult = $resultFail
        }
        #
        # Delete the snapshot
        #
        Write-LogInfo "Deleting Snapshot ${snapshot} of VM ${VMName}"
        Remove-VMSnapshot -VMName $VMName -Name $snapshot -ComputerName $HvServer

        if( $testResult -ne $resultFail) {
            Write-LogInfo "Only the first file is present. Test succeeded"
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

Main
