# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Save/Pause and resume the VM every 10 seconds and get the throughput 
    from iPerf3 each time. Make sure throughput doesn't drop to 0. If it
    does drop, check the VF count (it should be 1)
#>

param ([string] $TestParams)

function Main {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMPassword,
        $TestParams
    )
    $VMRootUser = "root"

    # Get IP
    $ipv4 = Get-IPv4ViaKVP $VMName $HvServer
    $vm2ipv4 = Get-IPv4ViaKVP $DependencyVmName $DependencyVmHost

    # Check parameter
    if ($TestParams.VM_STATE -eq "pause") {
        $cmd_StateChange = "Suspend-VM -Name `$VMName -ComputerName `$HvServer -Confirm:`$False"
        $cmd_StateResume = "Resume-VM -Name `$VMName -ComputerName `$HvServer -Confirm:`$False"
    } elseif ($TestParams.VM_STATE -eq "save") {
        $cmd_StateChange = "Save-VM -Name `$VMName -ComputerName `$HvServer -Confirm:`$False"
        $cmd_StateResume = "Start-VM -Name `$VMName -ComputerName `$HvServer -Confirm:`$False"
    } else {
        LogErr "Check the parameters! It should have VM_STATE=pause or VM_STATE=save"
        return "FAIL"
    }

    # Start client on dependency VM
    RunLinuxCmd -ip $vm2ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "iperf3 -s > client.out" -RunInBackGround
    Start-Sleep -s 5

    # Run iPerf on client side for 30 seconds with SR-IOV enabled
    RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "source sriov_constants.sh ; iperf3 -t 2400 -c `$VF_IP2 --logfile PerfResults.log" `
        -RunInBackGround
    Start-Sleep -s 30
    [decimal]$initialThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'" `
        -ignoreLinuxExitCode:$true
    if (-not $initialThroughput){
        LogErr "No result was logged! Check if iPerf was executed!"
        return "FAIL"
    }
    LogMsg "The throughput before starting the stress test is $initialThroughput Gbits/sec"
    [decimal]$initialThroughput = $initialThroughput * 0.7

    $isDone = $False
    [int]$counter = 0
    $expiration = (Get-Date).AddMinutes(30)
    while ($isDone -eq $False) {
        [int]$timeToSwitch = 0
        $counter++
        $hasSwitched = $false

        # Read the throughput before changing VM state
        [decimal]$vfBeforeThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
        $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'"

        # Change state
        Invoke-Expression $cmd_StateChange
        Start-Sleep -s 10
        # Resume initial state
        Invoke-Expression $cmd_StateResume
        Wait-VMState -VMName $VMName -HvServer $HvServer -VMState "Running"

        # Start measuring the time to switch between netvsc and VF
        # Throughput will also be measured
        while ($hasSwitched -eq $false){
            # This check is made to determine if 30 minutes have passed
            # The test ends once we get past by 30 minute mark
            if ((Get-Date) -gt $expiration) {
                $isDone = $true
                $hasSwitched = $true
                break
            }
            # Get the throughput
            [decimal]$vfAfterThroughput = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
                $VMPassword -command "tail -4 PerfResults.log | head -1 | awk '{print `$7}'"

            # Compare results with the ones taken before the stress test
            # If they are simillar, end the 'while loop' and proceed to another state change
            if (($vfAfterThroughput -ne $vfBeforeThroughput) -and ($vfAfterThroughput -ge $initialThroughput)){
                $hasSwitched = $true
            } else {
                # If they are not simillar, check the measured time
                # If it's bigger than 5 seconds, make an additional check, to see if the VF is running
                # If more than 5 seconds passed and also VF is not running, fail the test
                if ($timeToSwitch -gt 5){
                    $vfCount = RunLinuxCmd -ip $ipv4 -port $VMPort -username $VMRootUser -password `
                        $VMPassword -command "find /sys/devices -name net -a -ipath '*vmbus*' | grep -c pci" `
                        -ignoreLinuxExitCode:$true
                    if ($vfCount -lt 1) {
                        LogErr "On run ${counter}, VF is not present"
                        return "FAIL"
                    } else {
                        $hasSwitched = $true
                    }
                }
                Start-Sleep -s 1
            }
            $timeToSwitch++
        }
        LogMsg "Run $counter :: Time to switch between netvsc and VF was $timeToSwitch seconds. Throughput was $vfAfterThroughput gbps"
    }

    return "PASS"
}

Main -VMName $AllVMData.RoleName -hvServer $xmlConfig.config.Hyperv.Hosts.ChildNodes[0].ServerName `
    -VMPort $AllVMData.SSHPort -VMPassword $password `
    -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))