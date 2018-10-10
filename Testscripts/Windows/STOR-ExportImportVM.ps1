# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Verify that the VM export and import operations are working.

.Description
    This script exports the VM, imports it back, verifies that the imported
    VM has the snapshots also. Finally it deletes the imported VM.
#>

param([string] $TestParams)

function Main {
    param (
        $HvServer,
        $VMName,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir
    )

    $testCaseTimeout = 600
    #####################################################################
    #
    # Main script body
    #
    #####################################################################

    # Check input arguments
    if ($VMName -eq $null) {
        LogErr "VM name is null"
        return "FAIL"
    }

    if ($HvServer -eq $null) {
        LogErr "hvServer is null"
        return "FAIL"
    }

    # Change the working directory for the log files
    if (-not (Test-Path $RootDir)) {
        LogErr  "The directory `"${rootDir}`" does not exist"
        return "FAIL"
    }
    Set-Location $RootDir
    #
    # Check that the VM is present on the server and it is in running state.
    #
    $vm = Get-VM -Name $VMName -ComputerName $HvServer
    if (-not $vm) {
        LogErr "Cannot find VM ${vmName} on server ${hvServer}"
        return "FAIL"
    }

    #
    # Stop the VM in order to export it
    #
    while ($testCaseTimeout -gt 0) {
        Stop-VM -Name $VMName -ComputerName $HvServer -Force -Verbose

        if ( (Check-VMState -vmName $VMName -hvServer $HvServer ("Off"))) {
            break
        }

        Start-Sleep -seconds 2
        $testCaseTimeout -= 2
    }

    if ($testCaseTimeout -eq 0) {
        LogErr "Test case timed out waiting for VM to stop"
        return "FAIL"
    }

    #
    # Create a Snapshot before exporting the VM
    #
    Checkpoint-VM -Name $VMName -ComputerName $HvServer -SnapshotName "TestExport" -Confirm:$False
    if ($? -ne "True") {
        LogErr "Error while creating the snapshot"
        return "FAIL"
    }

    LogMsg "Successfully created a new snapshot before exporting the VM"

    $exportPath = (Get-VMHost).VirtualMachinePath + "\ExportTest\"
    $vmPath = $exportPath + $VMName + "\"

    #
    # Delete existing export, if any.
    #
    Remove-Item -Path $vmPath -Recurse -Force -ErrorAction SilentlyContinue

    #
    # Export the VM
    #
    Export-VM -Name $VMName -ComputerName $HvServer -Path $exportPath -Confirm:$False -Verbose
    if ($? -ne "True") {
        LogErr "Error while exporting the VM"
        return "FAIL"
    }

    LogMsg "VM ${vmName} exported successfully"

    #
    # Before importing the VM from exported folder, Delete the created snapshot from the orignal VM.
    #
    Get-VMSnapshot -VMName $VMName -ComputerName $HvServer -Name "TestExport" | Remove-VMSnapshot -Confirm:$False

    #
    # Save the GUID of exported VM.
    #
    $ExportedVM = Get-VM -Name $VMName -ComputerName $HvServer
    $ExportedVMID = $ExportedVM.VMId

    #
    # Import back the above exported VM
    #
    $osInfo = Get-WmiObject Win32_OperatingSystem -ComputerName $HvServer
    if (-not $osInfo) {
        LogErr "Unable to collect Operating System information"
        return "FAIL"
    }

    [int]$BuildNum = [convert]::ToInt32($osInfo.BuildNumber, 10)
    switch ($BuildNum) {
        {$_ -lt 10000} {
            # Server 2012 R2, 20012 and 2008R2
            $vmConfig = Get-Item "$vmPath\Virtual Machines\*.xml"
        }
        {$_ -ge 10000} {
            # Server 2016 or newer
            $vmConfig = Get-Item "$vmPath\Virtual Machines\*.VMCX"
        }
        Default {
            # An unsupported version of Windows Server
            "Error: Unsupported build of Windows Server"
            return "FAIL"
        }
    }

    LogMsg $vmConfig.fullname

    Import-VM -Path $vmConfig -ComputerName $HvServer -Copy "${vmPath}\Virtual Hard Disks" -Verbose -Confirm:$False -GenerateNewId
    if ($? -ne "True") {
        LogErr "Error while importing the VM"
        return "FAIL"
    }

    LogMsg "VM ${vmName} has been imported back successfully"

    #
    # Check that the imported VM has a snapshot 'TestExport', apply the snapshot and start the VM.
    #
    $VMs = Get-VM -Name $VMName -ComputerName $HvServer

    $newName = "Imported_" + $VMName

    foreach ($Vm in $VMs) {
        if ($ExportedVMID -ne $($Vm.VMId)) {
            $ImportedVM = $Vm.VMId
            Get-VM -Id $Vm.VMId | Rename-VM -NewName $newName
            break
        }
    }

    Get-VMSnapshot -VMName $newName -ComputerName $HvServer -Name "TestExport" | Restore-VMSnapshot -Confirm:$False -Verbose
    if ($? -ne "True") {
        LogErr "Error while applying the snapshot to imported VM $ImportedVM"
        return "FAIL"
    }

    #
    # Verify that the imported VM has started successfully
    #
    LogMsg "Starting the VM $newName and waiting for the heartbeat..."

    if ((Get-VM -ComputerName $HvServer -Name $newName).State -eq "Off") {
        Start-VM -ComputerName $HvServer -Name $newName
    }

    While ((Get-VM -ComputerName $HvServer -Name $newName).State -eq "On") {
        Start-Sleep -Seconds 5
    }

    do {
        Start-Sleep -Seconds 5
    } until ((Get-VMIntegrationService $newName | Where-Object {$_.name -eq "Heartbeat"}).PrimaryStatusDescription -eq "OK")

    LogMsg "Imported VM ${newName} has a snapshot TestExport, applied the snapshot and VM started successfully"
    Stop-VM -Name $newName -ComputerName $HvServer -Force -TurnOff
    if ($? -ne "True") {
        LogErr "Error while stopping the VM"
        return "FAIL"

        LogMsg "VM exported with a new snapshot and imported back successfully"
        #
        # Cleanup - stop the imported VM, remove it and delete the export folder.
        #
        Remove-VM -Name $newName -ComputerName $HvServer -Force -Verbose
        if ($? -ne "True") {
            LogErr "Error while removing the Imported VM"
            return "FAIL"
        }
        else {
            LogMsg "Imported VM removed, test completed"
            return "PASS"
        }

        Remove-Item -Path "${vmPath}" -Recurse -Force
        if ($? -ne "True") {
            LogErr "Error while deleting the export folder, trying again..."
            Remove-Item -Recurse -Path "${vmPath}" -Force
        }

        return "FAIL"
    }
}
Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
    -TestParams $TestParams
