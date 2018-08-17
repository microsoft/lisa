# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([string] $TestParams)

function Add-KVPEntries {
    param (
        [String] $VmIp, 
        [String] $VMPort,
        [String] $RootDir, 
        [String] $Pool, 
        [String] $Entries
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
    while [ `$counter -le $Entries ]; do
        ./`${kvp_client} append $Pool "`${key}`${counter}" "`${value}"
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
    RemoteCopy -uploadTo $VmIp -port $VMPort -files $filename -username $User -password $Password -upload
    $retVal = RunLinuxCmd -username $User -password $Password -ip $VmIp -port $VMPort -command  `
        "cd /home/${User} && chmod +x kvp_client* && chmod u+x ${filename} && ./${filename}" `
        -runAsSudo

    return $retVal
}

function Main {
    param (
        $VMName,
        $VMLocation,
        $Ipv4,
        $VMPort,
        $TestParams
    )
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    $params = $TestParams.Split(";")

    foreach ($p in $params) {
        $fields = $p.Split("=")
        switch ($fields[0].Trim()) {
            "Entries" { $entries = $fields[1].Trim() }
            "Pool" { $pool = $fields[1].Trim() }
            default  {}
        }
    }

    # Supported in RHEL7.5 ( no official release for now, might need update )
    $FeatureSupported = Get-VMFeatureSupportStatus $Ipv4 $VMPort $user $password "3.10.0-860"
    if ($FeatureSupported -ne $True) {
        LogMsg "Kernels older than 3.10.0-862 require LIS-4.x drivers."
        $lisDriversCmd = "rpm -qa | grep kmod-microsoft-hyper-v && rpm -qa | grep microsoft-hyper-v" 
        $checkExternal = .\Tools\plink.exe -C -pw $password -P $VMPort $user@$Ipv4 $lisDriversCmd
        if ($? -ne "True") {
            LogErr "Error: No LIS-4.x drivers detected. Skipping test."
            $testResult = "Aborted"
            $resultArr += $testResult
            $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
            return $currentTestResult.TestResult
        }
    }

    $retVal = Add-KVPEntries $Ipv4 $VMPort $RootDir $pool $entries
    if (-not $retVal) {
        LogErr "Failed to add new KVP entries on VM"
        $testResult = "FAIL"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult 
    }

    # Create a data exchange object and collect KVP data from the VM
    $vm = Get-WmiObject -ComputerName $VMLocation -Namespace root\virtualization\v2 `
        -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$VMName`'"
    if (-not $vm) {
        LogErr "Unable to get VM data for ${VMName} on ${VMLocation}"
        $testResult = "FAIL"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult 
    }

    $kvp = Get-WmiObject -ComputerName $VMLocation -Namespace root\virtualization\v2 `
        -Query "Associators of {$vm} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent"
    if (-not $kvp) {
        LogErr "Unable to retrieve KVP Exchange object for VM '${VMName}'"
        $testResult = "FAIL"
        $resultArr += $testResult
        $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
        return $currentTestResult.TestResult 
    }

    $retVal = RunLinuxCmd -username $user -password $password -ip $Ipv4 -port $VMPort -command  "ps aux | grep [k]vp"
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

Main -VMName $AllVMData.RoleName -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
        -VMLocation $xmlConfig.config.Hyperv.Host.ServerName -TestParams $TestParams
    
