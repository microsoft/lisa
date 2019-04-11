# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	Verify that demand changes with memory pressure inside the VM.
 Description:
	Verify that memory changes if multiple memory add/remove operations are done.
	Only 1 VM is required for this test.
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
        # Write out test Params
        Write-LogInfo "TestParams:'${testParams}'"
        Set-Location $WorkingDirectory
        $startupMem  = Convert-ToMemSize $testParams.startupMem $HvServer
        if ( $startupMem -le 0 )
        {
            Throw "Unable to convert startupMem to int64."
        }
        Write-LogInfo "startupMem : $startupMem"
        $appGitURL = $TestParams.appGitURL
        $appGitTag = $TestParams.appGitTag
        #Write-LogInfo "Tries $tries"
        Write-LogInfo "stress-ng url is $appGitURL"
        Write-LogInfo "stress-ng tag is $appGitTag"
        # Delete any previous summary.log file
        $summaryLog = "${vmName}_summary.log"
        Remove-Item $summaryLog -ErrorAction SilentlyContinue
        # Skip the test if host is lower than WS2016
        $BuildNumber = Get-HostBuildNumber $HvServer
        Write-LogInfo "BuildNumber: '$BuildNumber'"
        if ( $BuildNumber -eq 0 ) {
            Throw "Info: Feature is not supported"
        }
        elseif ($BuildNumber -lt 10500) {
            Throw "Info: Feature supported only on WS2016 and newer"
        }
        $VmInfo = Get-VM -Name $vmName -ComputerName $HvServer -ErrorAction SilentlyContinue
        if ( -not $VmInfo ) {
            Throw "VM $vmName does not exist"
        }
        Write-LogInfo "Checking if stress-ng is installed"
        $retVal = Publish-App "stress-ng" $Ipv4 $appGitURL $appGitTag $VMPort
        if ( -not $retVal ) {
            Throw "Stress-ng is not installed! Please install it before running the memory stress tests."
        }
        Write-LogInfo "Stress-ng is installed! Will begin running memory stress tests shortly."
        # Get memory stats from VmInfo
        Start-Sleep -s 10
        $sleepPeriod = 60
        # get VmInfo memory from host and guest
        while ( $sleepPeriod -gt 0 ) {
            [int64]$vm1BeforeAssigned = ($VmInfo.MemoryAssigned/1MB)
            [int64]$vm1BeforeDemand = ($VmInfo.MemoryDemand/1MB)
            $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
            [int64]$vm1BeforeIncrease = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
            Write-LogInfo "Free memory reported by guest VM before increase: $vm1BeforeIncrease"
            if ( $vm1BeforeAssigned -gt 0 -and $vm1BeforeDemand -gt 0 -and $vm1BeforeIncrease -gt 0 ) {
                break
            }
            $sleepPeriod-= 5
            Start-Sleep -s 5
        }
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0) -or ($vm1BeforeIncrease -le 0)) {
            Throw "vm1 $vmName reported 0 memory (assigned or demand)."
        }
        Write-LogInfo "Memory stats after $vmName started reporting"
        Write-LogInfo "${vmName}: assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        # Change 1 - Increase by 2048 MB(2147483648)
        $testMem = $startupMem + 2147483648
        # Set new memory value. Trying for 3 iterations
        for ($i=0; $i -lt 3; $i++) {
            Set-VMMemory -VMName $vmName -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-Sleep -s 5
            if ( $VmInfo.MemoryAssigned -eq $testMem ) {
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterIncrease = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
                Write-LogInfo "Free memory reported by guest VM after increase: $vm1AfterIncrease KB"
                break
            }
        }
        if ( $i -eq 3 ) {
            $testResult = $resultFail
            Throw "VM failed to change memory. LIS 4.1 or kernel version 4.4 required"
        }
        if ( $vm1AfterAssigned -ne ($testMem/1MB)) {
            Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
            $testResult = $resultFail
            Throw "Memory assigned doesn't match the memory set as parameter"
        }
        Write-LogInfo "Memory stats after $vmName memory was changed"
        Write-LogInfo "${vmName}: Initial Memory - $vm1BeforeIncrease KB :: After setting new value - $vm1AfterIncrease"
        if ( ($vm1AfterIncrease - $vm1BeforeIncrease) -le 2000000) {
            $testResult = $resultFail
            Throw  "Guest reports that memory value hasn't increased enough!"
        }
        Write-LogInfo "Memory stats after $vmName memory was increased by 2GB"
        Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        # Change 2 - Decrease by 2048 MB(2147483648)
        Start-Sleep -s 10
        $testMem = $testMem - 2147483648
        # Set new memory value.Trying for 3 iterations
        for ($i=0; $i -lt 3; $i++) {
            Set-VMMemory -VMName $vmName -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-Sleep -s 5
            if ( $VmInfo.MemoryAssigned -eq $testMem ) {
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterDecrease  =Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
                Write-LogInfo "Free memory reported by guest VM after decrease: $vm1AfterDecrease KB"
                break
            }
        }
        if ( $i -eq 3 ) {
            $testResult = $resultFail
            Throw "VM failed to change memory. LIS 4.1 or kernel version 4.4 required"
        }
        if ( $vm1AfterAssigned -ne ($testMem/1MB) ) {
            Write-LogInfo "Memory stats after $vm1Name memory was changed"
            Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
            $testResult = $resultFail
            Throw "Memory assigned doesn't match the memory set as parameter"
        }
        if (($vm1AfterIncrease - $vm1AfterDecrease) -le 2000000) {
            Write-LogInfo "Memory stats after $vmName memory was changed"
            Write-LogInfo "${vmName}: Initial Memory - $vm1AfterIncrease KB :: After setting new value - $vm1AfterDecrease KB"
            $testResult = $resultFail
            Throw "Guest reports that memory value hasn't decreased enough!"
        }
        Write-LogInfo "Memory stats after $vmName memory was decreased by 2GB"
        Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        # Change 3 - Increase by 1GB(1073741824)
        Start-Sleep -s 10
        $testMem = $testMem + 1073741824
        # Set new memory value.Trying for 3 iterations
        for ($i=0; $i -lt 3; $i++) {
            Set-VMMemory -VMName $vmName  -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-Sleep -s 5
            if ($VmInfo.MemoryAssigned -eq $testMem) {
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterIncrease   =Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
                Write-LogInfo "Free memory reported by guest VM guest VM after increase: $vm1AfterIncrease KB"
                break
            }
        }
        if ( $i -eq 3 ) {
            $testResult = $resultFail
            Throw "VM failed to change memory. LIS 4.1 or kernel version 4.4 required"
        }
        if ( $vm1AfterAssigned -ne ($testMem/1MB) ) {
            Write-LogInfo "Memory stats after $vm1Name memory was changed"
            Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
            $testResult = $resultFail
            Throw "Memory assigned doesn't match the memory set as parameter!"
        }
        if ( ($vm1AfterIncrease - $vm1AfterDecrease) -le 1000000) {
            Write-LogInfo "Memory stats after $vm1Name memory was changed"
            Write-LogInfo "${vmName}: Initial Memory - $vm1AfterDecrease KB :: After setting new value - $vm1AfterIncrease KB"
            $testResult = $resultFail
            Throw "Guest reports that memory value hasn't increased enough!"
        }
        Write-LogInfo "Memory stats after $vmName memory was increased by 1GB"
        Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        # Change 4 - Decrease by 2GB(2147483648)
        Start-Sleep -s 10
        $testMem = $testMem - 2147483648
        # Set new memory value. Trying for 3 iterations
        for ($i=0; $i -lt 3; $i++) {
            Set-VMMemory -VMName $vmName  -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-Sleep -s 5
            if ($VmInfo.MemoryAssigned -eq $testMem) {
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterDecrease =Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
                Write-LogInfo "Free memory reported by guest VM guest VM after increase: $vm1AfterDecrease KB"
                break
            }
        }
        if ($i -eq 3){
            $testResult = $resultFail
            Throw "VM failed to change memory. LIS 4.1 or kernel version 4.4 required"
        }
        if ( $vm1AfterAssigned -ne ($testMem/1MB) ) {
            Write-LogInfo "Memory stats after $vm1Name memory was changed"
            Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
            $testResult = $resultFail
            Throw "Memory assigned doesn't match the memory set as parameter!"
        }
        if ( ($vm1AfterIncrease - $vm1AfterDecrease) -le 2000000) {
            Write-LogInfo "Memory stats after $vmName memory was changed"
            Write-LogInfo "${vmName}: Initial Memory - $vm1AfterIncrease KB :: After setting new value - $vm1AfterDecrease KB"
            $testResult = $resultFail
            Throw  "Error: Guest reports that memory value hasn't decreased enough!"
        }
        Write-LogInfo "Memory stats after $vmName memory was decreased by 2GB"
        Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        # Send Command to consume
        $run = Start-StressNg -vmIpv4 $Ipv4 -VMSSHPort $VMPort
        if (-not $run) {
            Throw "Unable to start stress-ng for creating pressure on $vmName"
        }

        [int64]$vm1Demand = ($VmInfo.MemoryDemand/1MB)
        # sleep a few seconds so stress-ng starts and the memory assigned/demand gets updated
        Start-Sleep -s 80
        # get memory stats while stress-ng is running
        [int64]$vm1Assigned = ($VmInfo.MemoryAssigned/1MB)
        Write-LogInfo "Memory stats after $vmName started stress-ng"
        Write-LogInfo "${vmName}: assigned - $vm1Assigned"
        Write-LogInfo "${vmName}: demand - $vm1Demand"
        if ($vm1Demand -le $vm1BeforeDemand ) {
            Throw "Memory Demand did not increase after starting stress-ng"
        }
        # get memory stats after tool stress-ng stopped running
        [int64]$vm1AfterStressAssigned = ($VmInfo.MemoryAssigned/1MB)
        [int64]$vm1AfterStressDemand = ($VmInfo.MemoryDemand/1MB)
        Write-LogInfo "Memory stats after $vmName stress-ng run"
        Write-LogInfo "${vmName}: assigned - $vm1AfterStressAssigned | demand - $vm1AfterStressDemand"
        if ($vm1AfterStressDemand -ge $vm1Demand) {
            $testResult = $resultFail
            Throw  "Memory Demand did not decrease after stress-ng stopped"
        }
        Write-LogInfo "VM changed its memory and ran memory stress tests successfully!"
        $testResult = $resultPass
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "$ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -allVMData $AllVmData

