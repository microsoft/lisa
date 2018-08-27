# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Disable then enable the shutdown service and verify shutdown still works.

.Description
    Disable, then re-enable the LIS Shutdown service.  Then verify that
    a shutdown request still works. 
#>

param([String] $TestParams)

function Main {
    param (
        [String] $Ipv4,
        [String] $VMPort,
        [String] $VMName,
        [String] $HvServer,
        [String] $RootDir
    )

    if (-not (Test-Path $RootDir) ) {
        LogErr " The test root directory '${RootDir}' does not exist"
        return "FAIL"
    } else {
        Set-Location $RootDir
    }

    # Get the VMs Integrated Services and verify Shutdown is enabled and status is OK
    LogMsg " Verify the Integrated Services Shutdown Service is enabled"
    $status = Get-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name Shutdown
    if ($status.Enabled -ne $True) {
        LogErr " The Integrated Shutdown Service is already disabled"
        return "FAIL"
    }
    if ($status.PrimaryOperationalStatus -ne "Ok") {
        LogErr " Incorrect Operational Status for Shutdown Service: $($status.PrimaryOperationalStatus)"
        return "FAIL"
    }

    # Disable the Shutdown service
    LogMsg " Disabling the Integrated Services Shutdown Service"
    Disable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name Shutdown
    $status = Get-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name Shutdown
    if ($status.Enabled -ne $False) {
        LogErr " The Shutdown Service could not be disabled"
        return "FAIL"
    }
    if ($status.PrimaryOperationalStatus -ne "Ok") {
        LogErr " Incorrect Operational Status for Shutdown Service: $($status.PrimaryOperationalStatus)"
        return "FAIL"
    }
    LogMsg " Integrated Shutdown Service has been successfully disabled"

    # Enable the Shutdown service
    LogMsg " Enabling the Integrated Services Shutdown Service"
    Enable-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name Shutdown
    $status = Get-VMIntegrationService -ComputerName $HvServer -VMName $VMName -Name Shutdown
    if ($status.Enabled -ne $True) {
        LogErr " Integrated Shutdown Service could not be enabled!"
        return "FAIL"
    }
    if ($status.PrimaryOperationalStatus -ne "Ok") {
        LogErr " Incorrect Operational Status for Shutdown Service: $($status.PrimaryOperationalStatus)"
        return "FAIL"
    }
    LogMsg " Integrated Shutdown Service successfully Enabled"

    # Now do a shutdown to ensure the Shutdown Service is still functioning
    LogMsg " Shutting down the VM"
    $ShutdownTimeout = 600
    Stop-VM -Name $VMName -ComputerName $HvServer -Force
    while ($shutdownTimeout -gt 0) {
        if ((CheckVMState $VMName $HvServer) -eq "Off") {
            break
        }
        Start-Sleep -seconds 2
        $shutdownTimeout -= 2
    }

    if ($shutdownTimeout -eq 0) {
        LogErr " Shutdown timed out waiting for VM to go to Off state"
        return "FAIL"
    }
    LogMsg " VM ${VMName} Shutdown successful"

    # Now start the VM so the automation scripts can do what they need to do
    LogMsg " Starting the VM"
    Start-VM -Name $VMName -ComputerName $HvServer -Confirm:$false

    $startTimeout = 300
    while ($startTimeout -gt 0) {
        if ( (Test-TCP $Ipv4 $VMPort) -eq "True" ) {
            break
        }
        Start-Sleep -seconds 5
        $startTimeout -= 5
    }

    LogMsg " VM successfully started"

    # If we reached here, everything worked fine
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $xmlConfig.config.Hyperv.Host.ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -RootDir $WorkingDirectory -TestParams $TestParams

