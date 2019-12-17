# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Verify runtime memory hot add feature with Dynamic Memory disabled.

 Description:
    Verify that memory changes with non 128-MB aligned values. This test will
    start a vm with 4000 MB and will hot add 1000 MB to it. After that, will
    reboot the vm and hot add another 1000 MB. Test will pass if all hot add
    operations work.
#>
param([string] $testParams, [object] $AllVmData)
#######################################################################
#
# Main script body
#
#######################################################################
function Main {
    param (
        $testParams, $allVMData
    )
    $currentTestResult = Create-TestResultObject
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $vmName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4=$captureVMData.PublicIP
        $VMPort=$captureVMData.SSHPort
        Write-LogInfo "Test VM details :"
        Write-LogInfo "RoleName : $($captureVMData.RoleName)"
        Write-LogInfo "Public IP : $($captureVMData.PublicIP)"
        Write-LogInfo "SSH Port : $($captureVMData.SSHPort)"
        Write-LogInfo "HostName : $($captureVMData.HyperVhost)"
        Set-Location $WorkingDirectory
        Write-LogInfo "startup memory : $($testParams.startupMem)"
        # Parse the TestParams string, then process each parameter
        $startupMem = Convert-ToMemSize $testParams.startupMem $captureVMData.HyperVhost
        if ( $startupMem -le 0 )
        {
            Throw "Unable to convert startupMem to int64."
        }
        Write-LogInfo "startupMem: $startupMem"
        # Delete any previous summary.log file
        $summaryLog = "${vmName}_summary.log"
        Remove-Item $summaryLog -ErrorAction SilentlyContinue
        # Skip the test if host is lower than WS2016
        $BuildNumber = Get-HostBuildNumber $HvServer
        Write-LogInfo "BuildNumber: '$BuildNumber'"
        if ( $BuildNumber -eq 0 ) {
            Throw "Feature is not supported"
        }
        elseif ( $BuildNumber -lt 10500 ) {
            $testResult = "ABORTED"
            Throw "Feature supported only on WS2016 and newer"
        }
        $VmInfo = Get-VM -Name $vmName -ComputerName $HvServer -ErrorAction SilentlyContinue
        if ( -not $VmInfo) {
            Throw "VM $vmName does not exist"
        }
        # Get memory stats from vm1
        Start-Sleep -Seconds 60
        # Get VM1 memory from host and guest
        [int64]$vm1BeforeAssigned = ($VmInfo.MemoryAssigned/1MB)
        [int64]$vm1BeforeDemand = ($VmInfo.MemoryDemand/1MB)
        $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
        [int64]$vm1BeforeIncrease =Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
        Write-LogInfo "Free memory reported by guest VM before increase: $vm1BeforeIncrease"
        # Check memory values
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0) -or ($vm1BeforeIncrease -le 0)) {
            Throw "vm1 $vmName reported 0 memory (assigned or demand)."
        }
        Write-LogInfo "Memory stats after $vmName started reporting"
        Write-LogInfo "${vmName}: assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        # Change 1 - Increase memory by 1000MB(1048576000)
        $testMem = $startupMem + 1048576000
        # Set new memory value for 3 iterations
        for ($i=0; $i -lt 3; $i++) {
            Set-VMMemory -VMName $vmName  -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-Sleep -Seconds 5
            if ( $VmInfo.MemoryAssigned -eq $testMem ) {
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterIncrease =Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
                Write-LogInfo "Free memory reported by guest VM after first 1000MB increase: $vm1AfterIncrease KB"
                break
            }
        }
        if ( $i -eq 3 ) {
            $testResult = $resultFail
            Throw "VM failed to change memory. LIS 4.1 or kernel version 4.4 required"
        }
        if ($vm1AfterAssigned -ne ($testMem/1MB)) {
            Write-LogInfo "Memory stats after $vmName memory was changed"
            Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
            $testResult = $resultFail
            Throw "Memory assigned doesn't match the memory set as parameter!"
        }
        Write-LogInfo "Memory stats after $vmName memory was changed"
        Write-LogInfo "${vmName}: Initial Memory - $vm1BeforeIncrease KB :: After setting new value - $vm1AfterIncrease"
        #checking the value increased is less than 700000
        if ( ($vm1AfterIncrease - $vm1BeforeIncrease ) -le 700000) {
            $testResult = $resultFail
            Throw "Guest reports that memory value hasn't increased enough!"
        }
        Write-LogInfo "Memory stats after $vmName memory was increased by 1000MB"
        Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        # Restart VM
        $timeout=120
        Restart-VM -VMName $vmName -ComputerName $HvServer -Force
        $sts=Wait-ForVMToStartKVP $vmName $HvServer $timeout
        if( -not $sts[-1]) {
            $testResult = $resultFail
            Throw "VM $vmName has not booted after the restart" `
                    | Tee-Object -Append -file $summaryLog
        }
        # Increase memory again after reboot by 1000MB(1048576000 bytes)
        Start-Sleep -Seconds 60
        $testMem = $testMem + 1048576000
        # Set new memory value trying for 3 iterations
        for ($i=0; $i -lt 3; $i++) {
            Set-VMMemory -VMName $vmName -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-Sleep -Seconds 5
            if ( $VmInfo.MemoryAssigned -eq $testMem ) {
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterIncrease =Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
                Write-LogInfo "Free memory reported by guest VM after second 1000MB increase: $vm1AfterIncrease KB"
                break
            }
        }
        if ( $i -eq 3 ) {
            $lisDriversCmd="dmesg | grep hot_add"
            Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
            $testResult = $resultFail
            Throw "VM failed to change memory!"
        }
        Write-LogInfo "After reboot Memory stats $vmName memory was increased with 1000MB"
        Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        Write-LogInfo "Info: VM memory changed successfully!"
        $testResult = $resultPass
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    }
    finally{
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -allVMData $AllVmData
