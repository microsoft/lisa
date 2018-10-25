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
param([string] $TestParams)
#######################################################################
#
# Main script body
#
#######################################################################
function Main {
    param (
        $testParams
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
        Set-Location $WorkingDirectory
        LogMsg "startup memory : $($testParams.startupMem)"
        # Parse the TestParams string, then process each parameter
        $startupMem = Convert-ToMemSize $testParams.startupMem $captureVMData.HyperVhost
        if ( $startupMem -le 0 )
        {
            Throw "Unable to convert startupMem to int64."
        }
        LogMsg "startupMem: $startupMem"
        # Delete any previous summary.log file
        $summaryLog = "${vmName}_summary.log"
        Remove-Item $summaryLog -ErrorAction SilentlyContinue
        # Skip the test if host is lower than WS2016
        $BuildNumber = Get-HostBuildNumber $HvServer
        LogMsg "BuildNumber: '$BuildNumber'"
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
        Start-Sleep -s 60
        # Get VM1 memory from host and guest
        [int64]$vm1BeforeAssigned = ($VmInfo.MemoryAssigned/1MB)
        [int64]$vm1BeforeDemand = ($VmInfo.MemoryDemand/1MB)
        $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
        [int64]$vm1BeforeIncrease  = .\Tools\plink.exe -C -pw $password -P $VMPort $user@$Ipv4 $lisDriversCmd
        LogMsg "Free memory reported by guest VM before increase: $vm1BeforeIncrease"
        # Check memory values
        if (($vm1BeforeAssigned -le 0) -or ($vm1BeforeDemand -le 0) -or ($vm1BeforeIncrease -le 0)){
            Throw "vm1 $vmName reported 0 memory (assigned or demand)."
        }
        LogMsg "Memory stats after $vmName started reporting"
        LogMsg "${vmName}: assigned - $vm1BeforeAssigned | demand - $vm1BeforeDemand"
        # Change 1 - Increase memory by 1000MB(1048576000)
        $testMem = $startupMem + 1048576000
        # Set new memory value for 3 iterations
        for ($i=0; $i -le 3; $i++) {
            Set-VMMemory -VMName $vmName  -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-Sleep -s 5
            if ( $VmInfo.MemoryAssigned -eq $testMem ){
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterIncrease  = .\Tools\plink.exe -C -pw $password -P $VMPort $user@$Ipv4 $lisDriversCmd
                LogMsg "Free memory reported by guest VM after first 1000MB increase: $vm1AfterIncrease KB"
                break
            }
        }
        if ( $i -eq 3 ) {
            $testResult = $resultFail
            Throw "VM failed to change memory. LIS 4.1 or kernel version 4.4 required"
        }
        if ($vm1AfterAssigned -ne ($testMem/1MB)){
            LogMsg "Memory stats after $vmName memory was changed"
            LogMsg "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
            $testResult = $resultFail
            Throw "Memory assigned doesn't match the memory set as parameter!"
        }
        LogMsg "Memory stats after $vmName memory was changed"
        LogMsg "${vmName}: Initial Memory - $vm1BeforeIncrease KB :: After setting new value - $vm1AfterIncrease"
        #checking the value increased is less than 700000
        if ( ($vm1AfterIncrease - $vm1BeforeIncrease ) -le 700000) {
            $testResult = $resultFail
            Throw "Guest reports that memory value hasn't increased enough!"
        }
        LogMsg "Memory stats after $vmName memory was increased by 1000MB"
        LogMsg "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        # Restart VM
        $timeout=120
        Restart-VM -VMName $vmName -ComputerName $HvServer -Force
        $sts=Wait-ForVMToStartKVP $VMName1 $HvServer $timeout
        if( -not $sts[-1]) {
            $testResult = $resultFail
            Throw "VM $vmName has not booted after the restart" `
                    | Tee-Object -Append -file $summaryLog
        }
        # Increase memory again after reboot by 1000MB(1048576000 bytes)
        Start-Sleep -s 60
        $testMem = $testMem + 1048576000
        # Set new memory value trying for 3 iterations
        for ($i=0; $i -lt 3; $i++) {
            Set-VMMemory -VMName $vmName -ComputerName $HvServer -DynamicMemoryEnabled $false -StartupBytes $testMem
            Start-sleep -s 5
            if ( $VmInfo.MemoryAssigned -eq $testMem ) {
                [int64]$vm1AfterAssigned = ($VmInfo.MemoryAssigned/1MB)
                [int64]$vm1AfterDemand = ($VmInfo.MemoryDemand/1MB)
                $lisDriversCmd = "cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }'"
                [int64]$vm1AfterDecrease  = .\Tools\plink.exe -C -pw $password -P $VMPort $user@$Ipv4 $lisDriversCmd
                LogMsg "Free memory reported by guest VM after second 1000MB increase: $vm1AfterDecrease KB"
                break
            }
        }
        if ( $i -eq 3 ) {
            $lisDriversCmd="dmesg | grep hot_add"
            .\Tools\plink.exe -C -pw $password -P $VMPort $user@$Ipv4 $lisDriversCmd
            $testResult = $resultFail
            Throw "VM failed to change memory!"
        }
        LogMsg "After reboot Memory stats $vmName memory was increased with 1000MB"
        LogMsg "${vmName}: assigned - $vm1AfterAssigned | demand - $vm1AfterDemand"
        LogMsg "Info: VM memory changed successfully!"
        $testResult = $resultPass
    }
    catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "$ErrorMessage at line: $ErrorLine"
    }
    finally{
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
	$currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}
Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))