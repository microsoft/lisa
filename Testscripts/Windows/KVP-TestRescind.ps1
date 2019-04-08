# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Verify the KVP service and KVP daemon.

.Description
    Ensure the Data Exchange service is operational after a cycle
    of disable and reenable of the service. Additionally, check that
    the daemon is running on the VM.
#>

param([String] $TestParams,
      [object] $AllVmData)

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

    if (-not $TestParams) {
        Write-LogErr "Error: No test parameters specified"
        return "Aborted"
    }
    if (-not $RootDir) {
        Write-LogInfo "Warn : no rootdir was specified"
    } else {
        Set-Location $RootDir
    }

    # Debug - display the test parameters so they are captured in the log file
    Write-LogInfo "TestParams : '${TestParams}'"

    # Parse the test parameters
    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "ipv4"      { $ipv4    = $fields[1].Trim() }
            "CycleCount"    { $CycleCount = $fields[1].Trim() }
            default  {}
        }
    }

    $checkVM = Check-Systemd -Ipv4 $Ipv4 -SSHPort $VMPort -Username $VMUserName `
                    -Password $VmPassword
    if ( -not $checkVM[-1]) {
        Write-LogInfo "Systemd is not being used. Test Skipped"
        return "FAIL"
    }

    # Get KVP Service status
    $gsi = Get-VMIntegrationService -Name "Key-Value Pair Exchange" -VMName $VMName -ComputerName $hvServer
    if ($? -ne "True") {
        Write-LogInfo "Error: Unable to get Key-Value Pair status on $VMName ($hvServer)"
        return "FAIL"
    }

    # Check if VM is RedHat 7.3 or later (and if not, check external LIS exists)
    $supportkernel = "3.10.0.514" #kernel version for RHEL 7.3
    $null = .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$ipv4 "yum --version 2> /dev/null"
    if ($? -eq "True") {
        $kernelSupport = Get-VMFeatureSupportStatus -Ipv4 $ipv4 -SSHPort $VMPort -UserName $VMUserName `
                            -Password $VMPassword -SupportKernel $supportkernel
        if ($kernelSupport -ne "True") {
            Write-LogInfo "Info: Kernels older than 3.10.0-514 require LIS-4.x drivers."
            $null = .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$ipv4 `
                                "rpm -qa | grep kmod-microsoft-hyper-v && rpm -qa | grep microsoft-hyper-v"
            if ($? -ne "True") {
                Write-LogInfo "Error: No LIS-4.x drivers detected. Skipping test."
                return "FAIL"
            }
        }
    }

    # If KVP is not enabled, enable it
    if ($gsi.Enabled -ne "True") {
        Enable-VMIntegrationService -Name "Key-Value Pair Exchange" -VMName $VMName -ComputerName $hvServer
        if ($? -ne "True") {
            Write-LogErr "Error: Unable to enable Key-Value Pair on $VMName ($hvServer)"
            return "FAIL"
        }
    }

    # Disable and Enable KVP according to the given parameter
    $counter = 0
    while ($counter -lt $CycleCount) {
        Disable-VMIntegrationService -Name "Key-Value Pair Exchange" -VMName $VMName -ComputerName $hvServer
        if ($? -ne "True") {
            Write-LogErr "Error: Unable to disable VMIntegrationService on $VMName ($hvServer) on $counter run"
            return "FAIL"
        }
        Start-Sleep 5

        Enable-VMIntegrationService -Name "Key-Value Pair Exchange" -VMName $VMName -ComputerName $hvServer
        if ($? -ne "True") {
            Write-LogInfo "Error: Unable to enable VMIntegrationService on $VMName ($hvServer) on $counter run"
            return "FAIL"
        }
        Start-Sleep 5
        $counter += 1
    }

    Write-LogInfo "Disabled and Enabled KVP Exchange $counter times"

    #Check KVP service status after disable/enable
    $gsi = Get-VMIntegrationService -Name "Key-Value Pair Exchange" -VMName $VMName -ComputerName $hvServer
    if ($gsi.PrimaryOperationalStatus -ne "OK") {
        Write-LogInfo "Error: Key-Value Pair service is not operational after disable/enable cycle. `
        Current status: $gsi.PrimaryOperationalStatus"
        return "FAIL"
    } else {
        # Daemon name might vary. Get the correct daemon name based on systemctl output
        $daemonName = .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$ipv4 "systemctl list-unit-files | grep kvp"
        $daemonName = $daemonName.Split(".")[0]

        #If the KVP service is OK, check the KVP daemon on the VM
        $checkProcess = .\Tools\plink.exe -C -pw $VMPassword -P $VMPort $VMUserName@$ipv4 "systemctl is-active $daemonName"
        if ($checkProcess -ne "active") {
             Write-LogErr "Error: $daemonName is not running on $VMName after disable/enable cycle"
        } else {
            Write-LogInfo "Info: KVP service and $daemonName are operational after disable/enable cycle"
        }
    }

    # check selinux denied log after ip injection.
    $sts = Get-SelinuxAVCLog -ipv4 $ipv4 -SSHPort $VMPort -Username $VMUserName `
        -Password $VMPassword
    if (-not $sts) {
         return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -rootDir $WorkingDirectory `
         -testParams $testParams
