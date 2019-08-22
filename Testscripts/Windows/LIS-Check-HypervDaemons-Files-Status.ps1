# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    This script tests hyper-v daemons service status and files.

.Description
    The script will enable "Guest services" in "Integration Service" if it
    is disabled, then execute "Hyperv_Daemons_Files_Status" to check hypervkvpd,
    hypervvssd,hypervfcopyd status and default files.
'
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
        $RootDir
    )

    $gsi = $null
    $remoteScript = "LIS-Check-HypervDaemons-Files-Status.sh"
    #######################################################################
    #
    #	Main body script
    #
    #######################################################################

    # Checking the input arguments
    if (-not $VMName) {
        Write-LogErr "VM name is null!"
        return "FAIL"
    }

    if (-not $HvServer) {
        Write-LogErr "hvServer is null!"
        return "FAIL"
    }
    #
    # Change the working directory for the log files
    # Delete any previous summary.log file, then create a new one
    #
    if (-not (Test-Path $RootDir)) {
        Write-LogErr "The directory `"$RootDir}`" does not exist"
        return "FAIL"
    }
    Set-Location $RootDir
    # get host build number
    $BuildNumber = Get-HostBuildNumber -hvServer $HvServer

    if ($BuildNumber -eq 0) {
        return "FAIL"
    }
    # if lower than 9600, skip "Guest Service Interface" check
    if ($BuildNumber -ge 9600) {
        #
        # Verify if the Guest services are enabled for this VM
        #
        $gsi = Get-VMIntegrationService -vmName $VMName -ComputerName $HvServer -Name "Guest Service Interface"
        if (-not $gsi) {
            Write-LogErr "Unable to retrieve Integration Service status from VM '${VMName}'"
            return "FAIL"
        }

        if (-not $gsi.Enabled) {
            Write-LogWarn "The Guest services are not enabled for VM '${VMName}'"
            if ((Get-VM -ComputerName $HvServer -Name $VMName).State -ne "Off") {
                Stop-VM -ComputerName $HvServer -Name $VMName -Force -Confirm:$False
            }

            # Waiting until the VM is off
            Write-LogInfo "Turning off VM:'${VMname}'"
            while ((Get-VM -ComputerName $HvServer -Name $VMName).State -ne "Off") {
                Start-Sleep -Seconds 5
            }
            Write-LogInfo "Enabling  Guest services on VM:'${VMname}'"
            Enable-VMIntegrationService -Name "Guest Service Interface" -vmName $VMName -ComputerName $HvServer
            Write-LogInfo "Starting VM:'${VMname}'"
            Start-VM -Name $VMName -ComputerName $HvServer

            Write-LogInfo "Waiting for the VM to run again and respond to SSH - port"
            if (-not (Wait-ForVMToStartSSH -Ipv4addr $Ipv4 -StepTimeout 200)) {
                Write-LogErr "Test case timed out for VM to be running again!"
                return "FAIL"
            }
        }
    }
    #
    # Run the guest VM side script to verify floppy disk operations
    #
    $Hypervcheck = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > Hypervcheck.log`""
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort $Hypervcheck -runAsSudo
    $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $remoteScript.split(".")[0] -TestType "sh" `
        -PublicIP $Ipv4 -SSHPort $VMPort -Username $VMUserName -password $VMPassword `
        -TestName $currentTestData.testName
    $resultArr += $testResult
    Write-LogInfo "Test result : $testResult"
    $currentTestResult = Create-TestResultObject
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}
Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
    -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory
