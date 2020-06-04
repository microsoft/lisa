# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([String] $TestParams,
      [object] $AllVmData,
      [object] $CurrentTestData)

function Start-AzureVmNetwork {
    if ($TestPlatform -eq "Azure") {
        Add-Content restartNetwork.txt 'modprobe hv_netvsc; ip link set eth0 down; ip link set eth0 up; dhclient -r; dhclient'
        Invoke-AzureRmVMRunCommand  -ResourceGroupName $AllVMData.ResourceGroupName `
            -Name $AllVMData.RoleName -CommandId "RunShellScript" `
            -ScriptPath restartNetwork.txt
        Remove-Item restartNetwork.txt -Force
    }
}

function Check-Result {
    param (
        [String] $VmIp,
        [String] $VMPort,
        [String] $User,
        [String] $Password,
        [String] $VMName,
        [String] $HvServer
    )

    $retVal = $False
    $testRunning = "TestRunning"
    $testCompleted = "TestCompleted"
    $testAborted = "TestAborted"
    $testFailed = "TestFailed"
    $testSkipped = "TestSkipped"
    $attempts = 1

    $timeout = New-Timespan -Minutes 180
    $sw = [diagnostics.stopwatch]::StartNew()
    while ($sw.elapsed -lt $timeout){
        $state = $null
        Start-Sleep -Seconds 20
        Write-LogInfo "Test is running. Attempt number ${attempts} to reach VM"
        $attempts++
        $isVmAlive = Is-VmAlive -AllVMDataObject $AllVMData -MaxRetryCount 5
        if ($isVmAlive -eq "True") {
            if ($global:sshPrivateKey) {
                $sshKey = $global:sshPrivateKey
                $TestConnection = .\Tools\plink.exe -C -batch -i $sshKey -P $VMPort $User@$VmIp "echo Connected"
            } else {
                $TestConnection = .\Tools\plink.exe -C -batch -pw $Password -P $VMPort $User@$VmIp "echo Connected"
            }
            if ($TestConnection -eq "Connected") {
                $state = Run-LinuxCmd -ip $VmIp -port $VMPort -username $User -password $Password -command "cat state.txt" -ignoreLinuxExitCode:$true
                if (-not $state) {
                    if ($TestPlatform -eq "HyperV" -and (Get-VMIntegrationService $VMName -ComputerName $HvServer | `
                        Where-Object {$_.name -eq "Heartbeat"}).PrimaryStatusDescription `
                        -match "No Contact|Lost Communication") {

                        Stop-VM -Name $VMName -ComputerName $HvServer -Force -TurnOff
                        Write-LogErr "Lost Communication or No Contact to VM!"
                        break
                    } else {
                        Write-LogInfo "Current VM is inaccessible, please wait for a while."
                    }
                } else {
                    if ($state -eq $testRunning){
                        Write-LogInfo "Test is still running!"
                    } elseif (($state -eq $testCompleted) -or ($state -eq $testSkipped)) {
                        Write-LogInfo "state file contains ${state}"
                        $retVal = $True
                        break
                    } elseif (($state -eq $testAborted) -or ($state -eq $testFailed)) {
                        Write-LogErr "state file contains ${state}"
                        break
                    }
                }
            } else {
                Write-LogInfo "Current VM is inaccessible, please wait for a while."
                continue
            }
        } else {
            Write-LogInfo "Current VM is inaccessible, please wait for a while."
        }
    }
    if ($sw.elapsed -ge $timeout) {
        Start-AzureVmNetwork
        Write-LogErr "Test has timed out. After 3 hours, state file couldn't be read!"
    }
    Collect-TestLogs -LogsDestination $LogDir -ScriptName `
        $CurrentTestData.files.Split('\')[3].Split('.')[0] -TestType "sh" -PublicIP `
        $VmIp -SSHPort $VMPort -Username $User -password $Password -TestName `
        $CurrentTestData.testName | Out-Null
    return $retVal
}

#######################################################################
# Main script body
#######################################################################
function Main {
    param (
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $VMName,
        $HvServer
    )
    $testScript = "RELOAD-MODULES.sh"

    # Run test script in background
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
        -command "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;nohup bash ./${testScript} > RELOAD-MODULES_summary.log`"" -RunInBackGround | Out-Null

    $sts = Check-Result -VmIp $Ipv4 -VmPort $VMPort -User $VMUserName -Password $VMPassword -VMName $VMName -HvServer $HvServer
    if (-not $($sts[-1])) {
        Write-LogErr "Something went wrong during execution of $testScript script!"
        return "FAIL"
    } else {
        Write-LogInfo "Test Stress Reload Modules has passed"
        return "PASS"
    }
}

Main -VMName $AllVMData.RoleName -hvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory
