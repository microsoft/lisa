# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	Verify that memory assigned to VM changes when adding or removing a big amount (e.g. 2GB).
 Description:
    Verify that memory changes if a big chunk of memory is added or removed.
   Only 1 VM is required for this test.
#>
param([string] $TestParams)
#######################################################################
#
# Main script body
#
#######################################################################
function Main {
    param (
        $TestParams
    )
    try {
        $testResult = $null
        $captureVMData = $allVMData
        $vmName = $captureVMData.RoleName
        $HvServer= $captureVMData.HyperVhost
        $Ipv4=$captureVMData.PublicIP
        $VMPort=$captureVMData.SSHPort
        LogMsg "Test VM details :"
        LogMsg "RoleName : $($captureVMData.RoleName)"
        LogMsg "Public IP : $($captureVMData.PublicIP)"
        LogMsg "SSH Port : $($captureVMData.SSHPort)"
        LogMsg "HostName : $($captureVMData.HyperVhost)"
        LogMsg "startupMem :$($TestParams.startupMem)"
        LogMsg "TestMem : $($TestParams.testMem)"
        Set-Location $WorkingDirectory
        $testMem = Convert-ToMemSize $TestParams.testMem $captureVMData.HyperVhost
        if ($testMem -le 0)
        {
            Throw "Unable to convert testMem to int64."
        }
        LogMsg "testMem: $testMem"
        $startupMem = Convert-ToMemSize $TestParams.startupMem $captureVMData.HyperVhost
        if ($startupMem -le 0)
        {
            Throw "Unable to convert startupMem to int64."
        }
        LogMsg "startupMem: $startupMem"
        $appGitURL = $TestParams.appGitURL
        $appGitTag = $TestParams.appGitTag
        #LogMsg "Tries $tries"
        LogMsg "stress-ng url is $appGitURL"
        LogMsg "stress-ng tag is $appGitTag"
        # Delete any previous summary.log file
        $summaryLog = "${vmName}_summary.log"
        Remove-Item $summaryLog -ErrorAction SilentlyContinue
        # Skip the test if host is lower than WS2016
        $BuildNumber = Get-HostBuildNumber $HvServer
        LogMsg "BuildNumber: '$BuildNumber'"
        if ($BuildNumber -eq 0) {
            Throw "Feature is not supported"
        }
        elseif ($BuildNumber -lt 10500) {
            $testResult = "ABORTED"
            Throw "Feature supported only on WS2016 and newer"
        }
        $VmInfo = Get-VM -Name $vmName -ComputerName $HvServer -ErrorAction SilentlyContinue

        if (-not $VmInfo) {
            Throw "VM $vmName does not exist"
        }
        LogMsg "Checking if stress-ng is installed"
        $retVal = Publish-App "stress-ng" $Ipv4 $appGitURL $appGitTag $VMPort

        if (-not $retVal) {
            Throw "Stress-ng is not installed! Please install it before running the memory stress tests."
        }
        LogMsg "Stress-ng is installed! Will begin running memory stress tests shortly."
        # Get memory stats from $VmInfo
        Start-Sleep -s 10
        $sleepPeriod = 60
        # get VmInfo memory from host and guest
        while ($sleepPeriod -gt 0)
        {
            [int64]$vm1BeforeAssigned = ($VmInfo.MemoryAssigned/1MB)
            [int64]$vm1BeforeDemand = ($VmInfo.MemoryDemand/1MB)
            $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
            [int64]$vm1BeforeAssignedGuest =RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
            LogMsg "vm1BeforeAssignedGuest : '$vm1BeforeAssignedGuest'"
            if (($vm1BeforeAssigned -gt 0) -and ($vm1BeforeDemand -gt 0) -and ($vm1BeforeAssignedGuest -gt 0)){
                break
            }
            $sleepPeriod-= 5
            Start-Sleep -s 5
        }
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0) -or ($vm1BeforeAssignedGuest -le 0)){
            Throw "vm1 $vmName reported 0 memory (assigned or demand)."
        }
        LogMsg "Memory stats after $vmName started reporting"
        LogMsg "${vmName}: assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        # Setting new memory value for 3 iterations. To check memory has been increased or decreased for 3 iterations
        for ($i=0; $i -lt 3; $i++) {
            Set-VMMemory -VMName $vmName  -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-sleep -s 5
            if ($VmInfo.MemoryAssigned -eq $testMem){
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                # Get memory data from guest
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterAssignedGuest =RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command $lisDriversCmd -runAsSudo
                LogMsg "vm1AfterAssignedGuest : '$vm1AfterAssignedGuest'"
                break
            }
        }
        if ($i -eq 3) {
            $testResult = $resultFail
            Throw "VM failed to change memory. LIS 4.1 or kernel version 4.4 required"
        }
        LogMsg "Memory stats after $vmName memory was changed"
        LogMsg "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        if ( $vm1AfterAssigned -ne ($testMem/1MB)){
            $testResult = $resultFail
            Throw "Memory assigned doesn't match the memory set as parameter"
        }
        [int64]$deltaMemGuest = ($vm1BeforeAssignedGuest - $vm1AfterAssignedGuest) / 1024
        LogMsg "Free memory difference before-after assigning the new memory value: ${deltaMemGuest} MB"
        if ($testMem -ge $startupMem) {
            [int64]$deltaMemGuest = ($vm1AfterAssignedGuest - $vm1BeforeAssignedGuest) / 1024
        }
        else {
            [int64]$deltaMemGuest = ($vm1BeforeAssignedGuest - $vm1AfterAssignedGuest) / 1024
        }
        if ( $deltaMemGuest -lt 1000) {
            LogMsg "Memory stats after $vmName memory was changed"
            LogMsg "${vmName}: Initial Memory - $vm1BeforeAssignedGuest KB :: After setting new value - $vm1AfterAssignedGuest"
            $testResult = $resultFail
            Throw "Guest reports that memory value hasn't increased or decreased enough!"
        }
        LogMsg "Memory stats after $vmName memory was changed"
        LogMsg "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        LogMsg "Reported free memory inside ${vmName}: Before - $vm1BeforeAssignedGuest KB | After - $vm1AfterAssignedGuest KB"
        Start-StressNg -vmIpv4 $Ipv4 -VMSSHPort $VMPort
        if (-not $?) {
            Throw  "Unable to start stress-ng for creating pressure on $vmName"
        }
        [int64]$vm1Demand = ($VmInfo.MemoryDemand/1MB)
        # sleep a few seconds so stress-ng starts and the memory assigned/demand gets updated
        start-sleep -s 50
        # get memory stats while stress-ng is running
        [int64]$vm1Assigned = ($VmInfo.MemoryAssigned/1MB)
        LogMsg "Memory stats after $vmName started stress-ng"
        LogMsg "${vmName}: assigned - $vm1Assigned"
        LogMsg "${vmName}: demand - $vm1Demand"
        if ($vm1Demand -le $vm1BeforeDemand) {
            $testResult = $resultFail
            Throw "Memory Demand did not increase after starting stress-ng"
        }
        # get memory stats after stress-ng tool stopped running
        [int64]$vm1AfterStressAssigned = ($VmInfo.MemoryAssigned/1MB)
        [int64]$vm1AfterStressDemand = ($VmInfo.MemoryDemand/1MB)
        LogMsg "Memory stats after $vmName stress-ng run"
        LogMsg "${vmName}: assigned - $vm1AfterStressAssigned | demand - $vm1AfterStressDemand"
        if ($vm1AfterStressDemand -ge $vm1Demand) {
            LogMsg "Memory Demand did not decrease after stress-ng stopped"
        }
        LogMsg "VM changed its memory and ran memory stress tests successfully!"
        $testResult = $resultPass
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "$ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
	$currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
