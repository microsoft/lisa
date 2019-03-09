# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
 Description:
    Verify that demand changes with memory pressure by eatmemory inside the VM
    and vm does not crash.
#>

param([String] $TestParams, [object] $AllVmData)

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

    $filename = "CheckEatmemory.sh"
    $cmdToVM = @"
    #!/bin/bash
    count=0
    touch HotAddErrors.log
    echo "Info: eatmemory $vmConsumeMem MB" > HotAdd.log
    while true; do
        count=`$((`$count+1))
        echo "Info: eatmemory for `$count time" >> HotAdd.log
        eatmemory "${$vmConsumeMem}M"
        if [ `$? -nq 0 ]; then
            echo "Error: Cannot execute eatmemory $vmConsumeMem MB > HotAddErrors.log"
            exit 1
        fi
    done
    exit 0
"@

    # Install eatmemory if not installed
    $install = Publish-App -appName "eatmemory" -customIP $Ipv4 -appGitURL $TestParams.appGitURL -VMSSHPort $VMPort
    if (-not $install) {
        Write-LogErr "eatmemory could not be installed! Please install it before running the memory stress tests."
        return "FAIL"
    }
    else {
        Write-LogInfo "eatmemory is installed! Will begin running memory stress tests shortly."
    }

    $vm = Get-VM -Name $VMName -ComputerName $HvServer -ErrorAction SilentlyContinue
    $sleepPeriod = 120 #seconds
    # Get VM memory
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
        Write-LogErr "$VMName reported 0 memory (assigned or demand)."
        return "FAIL"
    }

    Write-LogInfo "Memory stats after $VMName started reporting "
    Write-LogInfo "${VMName}: assigned - $vmBeforeAssigned | demand - $vmBeforeDemand"

    [int64]$vmConsumeMem = (Get-VMMemory -VM $vm).Maximum

    # Transform to MB and stress with maximum
    $vmConsumeMem /= 1MB

    # Send Command to consume
    Add-Content $filename "$cmdToVM"
    Copy-RemoteFiles -uploadTo $Ipv4 -port $VMPort -files $filename -username $VMUserName -password $VMPassword -upload
    $eatmemory = "chmod u+x ${filename} && sed -i 's/\r//g' ${filename} && ./${filename}"
    $job1 = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort -command $eatmemory -runAsSudo -RunInBackGround
    if (-not $job1) {
        Write-LogErr  "Unable to start job for creating pressure on $VMName"
        return "FAIL"
    }

    # Wait for eatmemory to start and the memory assigned/demand gets updated
    $sleepTime = 30
    Start-Sleep -s $sleepTime

    #Get memory stats for vm after eatmemory starts
    [int64]$vmAssigned = ($vm.MemoryAssigned / 1MB)
    [int64]$vmDemand = ($vm.MemoryDemand / 1MB)

    Write-LogInfo "Memory stats before $VMName started eatmemory"
    Write-LogInfo " ${VMName}: assigned - $vmAssigned | demand - $vmDemand"

    if ($vmDemand -le $vmBeforeDemand) {
        Write-LogErr "Memory Demand did not increase after starting eatmemory"
        return "FAIL"
    }
    # Sleep for 3 minutes to wait for eatmemory runnning
    $sleepTime = 180
    Start-Sleep -s $sleepTime

    $isAlive = Wait-ForVMToStartKVP $VMName $HvServer 10
    if (-not $isAlive) {
        Write-LogErr  "VM is unresponsive after running the memory stress test"
        return "FAIL"
    }
    # Check for errors
    $errorfile = "${LogDir}\HotAddErrors.log"
    Copy-RemoteFiles -download -downloadFrom $Ipv4 -files "/home/${VMUserName}/HotAddErrors.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUserName -password $VMPassword
    $errorsOnGuest = Get-Content -Path $errorfile
    if (-not  [string]::IsNullOrEmpty($errorsOnGuest)) {
        Write-LogErr "Errors found while running eatmemory : $errorsOnGuest"
        return "FAIL"
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