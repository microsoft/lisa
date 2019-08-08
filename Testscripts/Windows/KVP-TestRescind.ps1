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
        Write-LogErr "No test parameters specified"
        return "Aborted"
    }
    if (-not $RootDir) {
        Write-LogWarn "No rootdir was specified"
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

    $checkVM = Check-Systemd -Ipv4 $Ipv4 -SSHPort $VMPort -Username $VMUserName -Password $VmPassword
    if ( -not $checkVM[-1]) {
        Write-LogInfo "Systemd is not being used. Test Skipped"
        return "SKIPPED"
    }

    # Get KVP Service status
    $gsi = Get-VMIntegrationService -Name $global:VMIntegrationKeyValuePairExchange -VMName $VMName -ComputerName $hvServer
    if ($? -ne "True") {
        Write-LogErr "Unable to get Key-Value Pair status on $VMName ($hvServer)"
        return "FAIL"
    }

    # Check if VM is RedHat 7.3 or later (and if not, check external LIS exists)
    if(@("REDHAT", "ORACLELINUX", "CENTOS").contains($global:detectedDistro)) {
        $supportkernel = "3.10.0.514" #kernel version for RHEL 7.3
        $kernelSupport = Get-VMFeatureSupportStatus -Ipv4 $ipv4 -SSHPort $VMPort -UserName $VMUserName `
                            -Password $VMPassword -SupportKernel $supportkernel
        if ($kernelSupport -ne "True") {
            Write-LogInfo "Kernels older than 3.10.0-514 require LIS-4.x drivers."
            $cmd = "rpm -qa | grep kmod-microsoft-hyper-v && rpm -qa | grep microsoft-hyper-v"
            $null = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $ipv4 -port $VMPort `
                -command $cmd -RunAsSudo -ignoreLinuxExitCode
            if (-not $?) {
                Write-LogErr "No LIS-4.x drivers detected."
                return "FAIL"
            }
        }
    }

    # If KVP is not enabled, enable it
    if ($gsi.Enabled -ne "True") {
        Enable-VMIntegrationService -Name $global:VMIntegrationKeyValuePairExchange -VMName $VMName -ComputerName $hvServer
        if ($? -ne "True") {
            Write-LogErr "Unable to enable Key-Value Pair on $VMName ($hvServer)"
            return "FAIL"
        }
    }

    # Disable and Enable KVP according to the given parameter
    $counter = 0
    while ($counter -lt $CycleCount) {
        Disable-VMIntegrationService -Name $global:VMIntegrationKeyValuePairExchange -VMName $VMName -ComputerName $hvServer
        if ($? -ne "True") {
            Write-LogErr "Unable to disable VMIntegrationService on $VMName ($hvServer) on $counter run"
            return "FAIL"
        }
        Start-Sleep 5

        Enable-VMIntegrationService -Name $global:VMIntegrationKeyValuePairExchange -VMName $VMName -ComputerName $hvServer
        if ($? -ne "True") {
            Write-LogInfo "Unable to enable VMIntegrationService on $VMName ($hvServer) on $counter run"
            return "FAIL"
        }
        Start-Sleep 5
        $counter += 1
    }

    Write-LogInfo "Disabled and Enabled KVP Exchange $counter times"

    #Check KVP service status after disable/enable
    $gsi = Get-VMIntegrationService -Name $global:VMIntegrationKeyValuePairExchange -VMName $VMName -ComputerName $hvServer
    if ($gsi.PrimaryOperationalStatus -ne "OK") {
        Write-LogErr "Key-Value Pair service is not operational after disable/enable cycle. `
        Current status: $($gsi.PrimaryOperationalStatus)"
        return "FAIL"
    } else {
        # Daemon name might vary. Get the correct daemon name based on systemctl output
        $daemonName = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $ipv4 -port $VMPort `
            -command "systemctl list-unit-files | grep kvp" -RunAsSudo
        $daemonName = $daemonName.Split(".")[0]

        #If the KVP service is OK, check the KVP daemon on the VM
        $checkProcess = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $ipv4 -port $VMPort `
            -command "systemctl is-active $daemonName" -RunAsSudo
        if ($checkProcess -ne "active") {
             Write-LogErr "$daemonName is not running on $VMName after disable/enable cycle"
             return "FAIL"
        } else {
            Write-LogInfo "KVP service and $daemonName are operational after disable/enable cycle"
        }
    }

    # check selinux denied log after ip injection.
    $sts = Get-SelinuxAVCLog -ipv4 $ipv4 -SSHPort $VMPort -Username $VMUserName -Password $VMPassword
    if (-not $sts) {
        Write-LogErr "Avc denied log is found in audit log"
        return "FAIL"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -rootDir $WorkingDirectory `
         -testParams $testParams
