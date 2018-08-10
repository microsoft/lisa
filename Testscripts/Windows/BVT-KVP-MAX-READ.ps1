# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([string] $testParams)

function Add-KVPEntries {
    param (
        [String] $VmIp, 
        [String] $sshKey, 
        [String] $rootDir, 
        [String] $pool, 
        [String] $entries
    )

    $cmdToVM = @"
    #!/bin/bash
    ps aux | grep "[k]vp"
    if [ `$? -ne 0 ]; then
      echo "KVP is disabled" >> /root/KVP.log 2>&1
      exit 1
    fi

    #
    # Verify OS architecture
    #
    uname -a | grep x86_64
    if [ `$? -eq 0 ]; then
        echo "64 bit architecture was detected"
        kvp_client="kvp_client64"
    else
        uname -a | grep i686
        if [ `$? -eq 0 ]; then
            echo "32 bit architecture was detected"
            kvp_client="kvp_client32" 
        else
            echo "Error: Unable to detect OS architecture" >> /root/KVP.log 2>&1
            exit 60
        fi
    fi

    value="value"
    counter=0
    key="test"
    while [ `$counter -le $entries ]; do
        ./`${kvp_client} append $pool "`${key}`${counter}" "`${value}"
        let counter=counter+1
    done

    if [ `$? -ne 0 ]; then
        echo "Failed to append new entries" >> /root/KVP.log 2>&1
        exit 100
    fi

    ps aux | grep "[k]vp"
    if [ `$? -ne 0 ]; then
        echo "KVP daemon failed after append" >> /root/KVP.log 2>&1
        exit 100
    fi

"@
    $filename = "AddKVPEntries.sh"
    if (Test-Path ".\${filename}") {
        Remove-Item ".\${filename}"
    }
    Add-Content $filename "$cmdToVM"

    # Send file
    RemoteCopy -uploadTo $VmIp -port $VmPort -files $filename -username $User -password $Password -upload
    $retVal = RunLinuxCmd -username $User -password $Password -ip $VmIp -port $VmPort -command  `
        "cd /home/${User} && chmod +x kvp_client* && chmod u+x ${filename} && dos2unix ${filename} && ./${filename}" `
        -runAsSudo

    return $retVal
}

#######################################################################
#
# Main script body
#
#######################################################################
function Main {
    $currentTestResult = CreateTestResultObject
    $resultArr = @()
    $ipv4 = $AllVMData.PublicIP
    $vmPort = $AllVMData.SSHPort
    $vmLocation = $xmlConfig.config.Hyperv.Host.ServerName
    $vmName = $AllVMData.RoleName
    $params = $testParams.Split(";")

    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "Entries" { $entries = $fields[1].Trim() }
            "Pool" { $pool = $fields[1].Trim() }
            default  {}
        }
    }

    # Source BVT-UTILS.ps1 for common functions
    if (Test-Path ".\Testscripts\Windows\BVT-UTILS.ps1") {
        . .\Testscripts\Windows\BVT-UTILS.ps1
        LogMsg "Info: Sourced BVT-UTILS.ps1"
    } else {
        LogErr "Error: Could not find Testscripts\Windows\BVT-UTILS.ps1"
        $testResult = "Aborted"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult
    }

    # Supported in RHEL7.5 ( no official release for now, might need update )
    $FeatureSupported = Get-VMFeatureSupportStatus $ipv4 $vmPort $user $password "3.10.0-860"
    if ($FeatureSupported -ne $True) {
        LogMsg "Kernels older than 3.10.0-862 require LIS-4.x drivers."
        $lisDriversCmd = "rpm -qa | grep kmod-microsoft-hyper-v && rpm -qa | grep microsoft-hyper-v" 
        $checkExternal = .\Tools\plink.exe -C -pw $password -P $vmPort $user@$ipv4 $lisDriversCmd
        if ($? -ne "True") {
            LogErr "Error: No LIS-4.x drivers detected. Skipping test."
            $testResult = "Aborted"
            $resultArr += $testResult
            $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
            return $currentTestResult.TestResult
        }
    }

    $retVal = Add-KVPEntries $ipv4 $sshKey $rootDir $pool $entries
    if (-not $retVal) {
        LogErr "Failed to add new KVP entries on VM"
        $testResult = "FAIL"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult 
    }

    # Create a data exchange object and collect KVP data from the VM
    $Vm = Get-WmiObject -ComputerName $vmLocation -Namespace root\virtualization\v2 -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$vmName`'"
    if (-not $Vm) {
        LogErr "Unable to get VM data for ${vmName} on ${vmLocation}"
        $testResult = "FAIL"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult 
    }

    $Kvp = Get-WmiObject -ComputerName $vmLocation -Namespace root\virtualization\v2 -Query "Associators of {$Vm} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent"
    if (-not $Kvp) {
        LogErr "Unable to retrieve KVP Exchange object for VM '${vmName}'"
        $testResult = "FAIL"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult 
    }

    $retVal = RunLinuxCmd -username $user -password $password -ip $ipv4 -port $vmPort -command  "ps aux | grep [k]vp"
    if (-not $retVal) {
        LogErr "KVP daemon crashed durring read process"
        $testResult = "FAIL"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult 
    } else {
        LogMsg "KVP daemon is running. Test Passed"
        $testResult = "PASS"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult    
    }   
}

Main
