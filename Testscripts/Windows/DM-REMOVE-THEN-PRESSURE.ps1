# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
 Verify that a VM's assigned memory could decrease when no pressure available.
 Then do stress test, assigned and demand memory
 could increase.
.DESCRIPTION
    Step 1: Verify that a VM's assigned memory could decrease when no pressure available.
    After VM sleeps less than 7 minutes, it is higher than minimum memory.
    Step 2: Do stress-ng test, during stress test, assigned and demand memory increase
    Step 3: After stress test, check that assigned and memory decrease again, no any crash in VM.

 Note: the startupMem shall be set as larger, e.g. same with maxMem.
#>

param([String] $TestParams,[object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMUserName,
        $VMPassword,
        $VMPort,
        $TestParams
    )

    $filename = "ConsumeMem.sh"
    $cmdToVM = @"
    #!/bin/bash
        __freeMem=`$(cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }')
        __freeMem=`$((__freeMem/1024))
        echo ConsumeMemory: Free Memory found `$__freeMem MB >> /home/$VMUserName/ConsumeMem.log 2>&1
        __threads=32
        __chunks=`$((`$__freeMem / `$__threads))
        echo "Going to start `$__threads instance(s) of stress-ng every 2 seconds, each consuming `$__chunks MB memory" >> /home/$VMUserName/ConsumeMem.log 2>&1
        stress-ng -m `$__threads --vm-bytes `${__chunks}M -t 120 --backoff 1500000
        echo "Waiting for jobs to finish" >> /home/$VMUserName/ConsumeMem.log 2>&1
        wait
        exit 0
"@

    # Install stress-ng if not installed
    $install = Publish-App  -appName "stress-ng" -customIP $Ipv4 -appGitURL $TestParams.appGitURL -appGitTag $TestParams.appGitTag -VMSSHPort $VMPort
    if (-not $install) {
        Write-LogInfo "stress-ng is could not be installed! Please install it before running the memory stress tests."
        return "FAIL"
    }
    else {
        Write-LogInfo "Stress-ng is installed! Will begin running memory stress tests shortly."
    }


    $vm = Get-VM -Name $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue

    # Get VM's minimum memory setting
    [int64]$vmMinMem = ($vm.MemoryMinimum / 1MB)
    Write-LogInfo "Minimum memory for $VMName is $vmMinMem MB"
    $sleepPeriod = 120 #seconds
    # Get VM's memory after MemoryDemand available
    while ($sleepPeriod -gt 0) {
        [int64]$vmBeforeAssigned = ($vm.MemoryAssigned / 1MB)
        [int64]$vmBeforeDemand = ($vm.MemoryDemand / 1MB)

        if ($vmBeforeAssigned -gt 0 -and $vmBeforeDemand -gt 0) {
            break
        }

        $sleepPeriod -= 5
        Start-Sleep -s 5
    }

    if ($vmBeforeAssigned -le 0 -or $vmBeforeDemand -le 0) {
        Write-LogErr "VM $VMName reported 0 memory (assigned or demand)."
        return "FAIL"
    }

    # Step 1: Verify assigned memory could decrease after sleep a while
    Write-LogInfo "Memory stats after $VMName just boots up"
    Write-LogInfo "${VMName}: assigned - $vmBeforeAssigned | demand - $vmBeforeDemand"

    $sleepPeriod = 0 #seconds

    while ($sleepPeriod -lt 420) {
        [int64]$vmAssigned = ($vm.MemoryAssigned / 1MB)
        [int64]$vmDemand = ($vm.MemoryDemand / 1MB)
        if ( $vmAssigned -lt $vmBeforeAssigned) {
            break
        }
        $sleepPeriod += 5
        Start-Sleep -s 5
    }

    Write-LogInfo "Memory stats after ${VMName} sleeps $sleepPeriod seconds"
    Write-LogInfo "${VMName}: assigned - $vmAssigned | demand - $vmDemand"

    # Verify assigned memory and demand decrease after sleep for a while
    if ($vmAssigned -ge $vmBeforeAssigned -or $vmDemand -ge $vmBeforeDemand ) {
        Write-LogErr "${VMName} assigned or demand memory does not decrease after sleep $sleepPeriod seconds"
        return "FAIL"
    }
    else {
        Write-LogInfo "${VMName} assigned and demand memory decreases after sleep $sleepPeriod seconds"
    }

    # Step 2: Test assigned/demand memory could increase during stress test

    # Sleep 2 more minutes to wait for the assigned memory decrease
    Start-Sleep -s 120

    [int64]$vmBeforeAssigned = ($vm.MemoryAssigned / 1MB)
    [int64]$vmBeforeAssigned = ($vm.MemoryDemand / 1MB)

    # Verify assigned memory does not drop below minimum memory
    if ($vmBeforeAssigned -lt $vmMinMem) {
        Write-LogErr "$VMName assigned memory drops below minimum memory set, $vmMinMem MB"
        return "FAIL"
    }
    Write-LogInfo "Memory stats before $VMName started stress-ng"
    Write-LogInfo "${VMName}: assigned - $vmBeforeAssigned | demand - $vmBeforeAssigned"

    # Send Command to consume
    Add-Content $filename "$cmdToVM"
    Copy-RemoteFiles -uploadTo $Ipv4 -port $VMPort -files $filename -username $VMUserName -password $VMPassword -upload
    $consume = "cd /home/$VMUserName && chmod u+x ${filename} && sed -i 's/\r//g' ${filename} && ./${filename}"
    $job1 = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort -command $consume -runAsSudo -RunInBackGround
    if (-not $job1) {
        Write-LogErr "Unable to start job for creating pressure on $VMName"
        return "FAIL"
    }

    # Sleep a few seconds so stress-ng starts and the memory assigned/demand gets updated
    start-sleep -s 50

    # Get memory stats while stress-ng is running
    [int64]$vmDemand = ($vm.MemoryDemand / 1MB)
    [int64]$vmAssigned = ($vm.MemoryAssigned / 1MB)
    Write-LogInfo "Memory stats after $VMName started stress-ng"
    Write-LogInfo "${VMName}: assigned - $vmAssigned | demand - $vmDemand"

    if ($vmDemand -le $vmBeforeDemand -or $vmAssigned -le $vmBeforeAssigned) {
        Write-LogErr "Memory assigned or demand did not increase after starting stress-ng"
        return "FAIL"
    }
    else {
        Write-LogInfo "${VMName} assigned and demand memory increased after starting stress-ng"
    }

    # Wait for jobs to finish now and make sure they exited successfully
    $timeout = 120
    $firstJobStatus = $false
    while ($timeout -gt 0) {
        if ($job1.Status -like "Completed") {
            $firstJobStatus = $true
            $retVal = Receive-Job $job1
            if (-not $retVal[-1]) {
                Write-LogErr "Consume Memory script returned false on VM $VMName"
                return "FAIL"
            }
        }

        if ($firstJobStatus) {
            break
        }

        $timeout -= 1
        start-sleep -s 1
    }

    # Step3: Verify assigned/demand memory could decrease again after stress test finished
    # Get VM's memory
    while ($sleepPeriod -lt 420) {
        [int64]$vmAfterAssigned = ($vm.MemoryAssigned / 1MB)
        [int64]$vmAfterDemand = ($vm.MemoryDemand / 1MB)
        if ( $vmAfterAssigned -lt $vmAssigned) {
            break
        }
        $sleepPeriod += 5
        Start-Sleep -s 5
    }

    Write-LogInfo "Memory stats after ${VMName} sleeps $sleepPeriod seconds"
    Write-LogInfo "${VMName}: assigned - $vmAfterAssigned | demand - $vmAfterDemand"

    # Verify assigned memory and demand decrease after sleep less than 7 minutes
    if ($vmAfterAssigned -ge $vmAssigned -or $vmAfterDemand -ge $vmDemand ) {
        Write-LogErr "${VMName} assigned or demand memory does not decrease after stress-ng stopped"
        return "FAIL"
    }
    else {
        Write-LogErr "${VMName} assigned and demand memory decreases after stress-ng stopped"
    }

    # Wait for 2 minutes and check call traces
    $trace = "${LogDir}\check_traces.log"
    Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort ". utils.sh && UtilsInit && CheckCallTracesWithDelay 120" -runAsSudo
    Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/check_traces.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    $contents = Get-Content -Path $trace
    if ($contents -contains "ERROR") {
        Write-LogErr "Test FAIL , Call Traces found!"
        return "FAIL"
    }
    else {
        Write-LogInfo "Test PASSED , No call traces found!"
    }
}
Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
    -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory`
    -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
