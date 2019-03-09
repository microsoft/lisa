# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	Verify that can remove memory while stress tool is running.

 Description:
    Verify that memory changes while stress tool is running.
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
        # change working directory to root dir
        Set-Location $WorkingDirectory
        Write-LogInfo "startup memory : $($testParams.startupMem)"
        $startupMem = Convert-ToMemSize $testParams.startupMem $captureVMData.HyperVhost
        if ($startupMem -le 0)
        {
            throw "Invalid startup memory"
        }
        Write-LogInfo "startupMem: $startupMem"
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
        # Check if stress-ng is installed
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
            [int64]$vm1BeforeAssignedGuest = Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
            if (($vm1BeforeAssigned -gt 0) -and ($vm1BeforeDemand -gt 0) -and ($vm1BeforeAssignedGuest -gt 0)) {
                break
            }
            $sleepPeriod-= 5
            Start-Sleep -s 5
        }
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0) -or ($vm1BeforeAssignedGuest -le 0)) {
            Throw "vm1 $vmName reported 0 memory (assigned or demand)."
        }
        Write-LogInfo "Memory stats after $vmName started reporting"
        Write-LogInfo "${vmName}: assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        # Send Command to consume
        $run = Start-StressNg -vmIpv4 $Ipv4 -VMSSHPort $VMPort
        if ( -not $run ) {
            Throw "Unable to start stress-ng for creating pressure on $vmName"
        }
        [int64]$vm1Demand = ($VmInfo.MemoryDemand/1MB)
        # sleep a few seconds so stress-ng starts and the memory assigned/demand gets updated
        Start-Sleep -s 80
        # get memory stats while stress-ng is running
        [int64]$vm1Assigned = ($VmInfo.MemoryAssigned/1MB)
        Write-LogInfo "Memory stats after $vm1Name started stress-ng"
        Write-LogInfo "${vmName}: assigned - $vm1Assigned"
        Write-LogInfo "${vmName}: demand - $vm1Demand"
        if ( $vm1Demand -le $vm1BeforeDemand ) {
            $testResult = $resultFail
            Throw "Memory Demand did not increase after starting stress-ng"
        }
        # Memory value to be assigned will be 300mb(314572800) higher than memory demand. divide 1 MB(1048576)
        [int64]$testMem = $VmInfo.MemoryDemand + 314572800
        # Adjust testMem value if it's not an even number
        [int64]$testMem = $testMem / 1048576
        if ( $testMem % 2 -eq 0 ){
            [int64]$testMem = $testMem * 1048576
        }
        else{
            [int64]$testMem = $testMem + 1
            [int64]$testMem = $testMem * 1048576
        }
        # Set new memory value. Trying for 3 iterations to set a new memory value
        for ($i=0; $i -lt 3; $i++) {
            Set-VMMemory -VMName $vmName  -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-Sleep -s 5
            if ( $VmInfo.MemoryAssigned -eq $testMem ){
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterAssignedGuest =Run-LinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
                break
            }
        }
        [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
        if ( $vm1AfterAssigned -eq $vm1BeforeAssigned ) {
            $testResult = $resultFail
            Throw "VM failed to change memory. LIS 4.1 or kernel version 4.4 required"
        }
        Write-LogInfo "Memory stats after $vmName memory was changed"
        Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        if ( $vm1AfterAssigned -ne ($testMem/1MB)) {
            $testResult = $resultFail
            Throw "Memory assigned doesn't match the memory set as parameter!"
        }
        Write-LogInfo "Memory stats after $vmName memory was changed"
        Write-LogInfo "${vmName}: Initial Memory - $vm1BeforeAssignedGuest KB :: After setting new value - $vm1AfterAssignedGuest KB"
        if ( $vm1AfterAssignedGuest -ge $vm1BeforeAssignedGuest ) {
            $testResult = $resultFail
            Throw "Guest reports that memory value hasn't decreased!"
        }
        Write-LogInfo "Memory stats after $vmName memory was changed"
        Write-LogInfo "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        Write-LogInfo "Reported free memory inside ${vmName}: Before - $vm1BeforeAssignedGuest KB | After - $vm1AfterAssignedGuest KB"
        # get memory stats after stress-ng stopped running
        [int64]$vm1AfterStressAssigned = ($VmInfo.MemoryAssigned/1MB)
        [int64]$vm1AfterStressDemand = ($VmInfo.MemoryDemand/1MB)
        Write-LogInfo "Memory stats after $vmName stress-ng run"
        Write-LogInfo "${vmName}: assigned - $vm1AfterStressAssigned | demand - $vm1AfterStressDemand"
        if ( $vm1AfterStressDemand -ge $vm1Demand ) {
            $testResult = $resultFail
            Throw "Memory Demand did not decrease after stress-ng stopped"
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
        if ( !$testResult ) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n")) -allVMData $AllVmData
