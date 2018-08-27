# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Disable then enable the Time Sync service and verify Time Sync still works.

.Description
    Disable, then re-enable the LIS Time Sync service. Then also save the VM and
    verify that after these operations a Time Sync request still works.
    The XML test case definition for this test would look similar to:
#>

param([String] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $TestParams
    )

    $tcCovered = "Undefined"
    $service = "Time Synchronization"

    if ($TestParams -eq $null) {
        LogErr " TestParams is null"
        return "FAIL"
    }

    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "TC_COVERED" { $tcCovered = $fields[1].Trim() }
            "MaxTimeDiff" { $maxTimeDiff = $fields[1].Trim() }
            default  {}
        }
    }

    if (-not $RootDir) {
        LogErr " The RootDir test parameter is not defined."
        return "Aborted"
    }

    if (-not (Test-Path $RootDir) ) {
        LogErr " The test root directory '${RootDir}' does not exist"
        return "FAIL"
    } else {
        Set-Location $RootDir
    }

    $retVal = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "bash ./CORE-ConfigTimeSync.sh" -runAsSudo
    if (-not $retVal) {
        LogErr " Failed to config time sync."
        return "FAIL"
    }

    # Get the VMs Integrated Services and verify Time Sync is enabled and status is OK
    LogMsg " Verify the Integrated Services Time Sync Service is enabled"
    $status = Get-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $service
    if ($status.Enabled -ne $True) {
        LogErr " The Integrated Time Sync Service is already disabled"
        return "FAIL"
    }
    if ($status.PrimaryOperationalStatus -ne "Ok") {
        LogErr " Incorrect Operational Status for Time Sync Service: $($status.PrimaryOperationalStatus)"
        return "FAIL"
    }

    # Disable the Time Sync service.
    LogMsg " Disabling the Integrated Services Time Sync Service"
    Disable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $service
    $status = Get-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $service
    if ($status.Enabled -ne $False) {
        LogErr " The Time Sync Service could not be disabled"
        return "FAIL"
    }
    if ($status.PrimaryOperationalStatus -ne "Ok") {
        LogErr " Incorrect Operational Status for Time Sync Service: $($status.PrimaryOperationalStatus)"
        return "FAIL"
    }
    LogMsg " Integrated Time Sync Service successfully disabled"

    # Enable the Time Sync service
    LogMsg " Enabling the Integrated Services Time Sync Service"

    Enable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $service
    $status = Get-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name $service
    if ($status.Enabled -ne $True) {
        LogErr " Integrated Time Sync Service could not be enabled"
        return "FAIL"
    }

    if ($status.PrimaryOperationalStatus -ne "Ok") {
        LogErr " Incorrect Operational Status for Time Sync Service: $($status.PrimaryOperationalStatus)"
        return "FAIL"
    }
    LogMsg " Integrated Time Sync Service successfully Enabled"

    Start-Sleep -seconds 5
    # Now also save the VM for 60 seconds
    LogMsg " Saving the VM"

    Save-VM -Name $VMName -ComputerName $HvServer -Confirm:$False
    Start-Sleep -seconds 60

    # Now start the VM so the automation scripts can do what they need to do
    LogMsg "Starting the VM"
    Start-VM -Name $VMName -ComputerName $HvServer -Confirm:$false
    $startTimeout = 300
    while ($startTimeout -gt 0) {
        if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
            break
        }
        Start-Sleep -seconds 5
        $startTimeout -= 5
    }
    if ($startTimeout -eq 0) {
        LogErr "Test case timed out for VM to enter in the Running state"
        return "FAIL"
    }
    LogMsg " VM successfully started"

    $diffInSeconds = Get-TimeSync -Ipv4 $Ipv4 -Port $VMPort `
                        -Username $VMUserName -Password $VMPassword
    
    if ($diffInSeconds -and ($diffInSeconds -lt $maxTimeDiff)) {
        LogMsg "Time is properly synced"
        return "PASS"
    } else {
        LogErr " Time is out of sync!"
        return "FAIL"
    }
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
         -TestParams $TestParams
