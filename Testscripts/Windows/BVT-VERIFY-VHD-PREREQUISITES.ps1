# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData, [object] $CurrentTestData)

function Main {
    param([object] $AllVMData, [object] $CurrentTestData)
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        $testScript = "BVT-VERIFY-VHD-PREREQUISITES.py"

        $detectedDistro = Detect-LinuxDistro -VIP $AllVMData.PublicIP -SSHport $AllVMData.SSHPort -testVMUser $user -testVMPassword $password
        if ($detectedDistro -imatch "UBUNTU") {
            $matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_GRUB_VERIFICATION_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE")
        }
        if ($detectedDistro -imatch "DEBIAN") {
            $matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE")
        }
        elseif ($detectedDistro -imatch "SUSE") {
            $matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_GRUB_VERIFICATION_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE")
        }
        elseif ($detectedDistro -imatch "CENTOS") {
            $matchstrings = @("_TEST_NETWORK_MANAGER_NOT_INSTALLED","_TEST_NETWORK_FILE_SUCCESS", "_TEST_IFCFG_ETH0_FILE_SUCCESS", "_TEST_UDEV_RULES_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE", "_TEST_GRUB_VERIFICATION_SUCCESS")
        }
        elseif ($detectedDistro -imatch "ORACLELINUX") {
            $matchstrings = @("_TEST_NETWORK_MANAGER_NOT_INSTALLED","_TEST_NETWORK_FILE_SUCCESS", "_TEST_IFCFG_ETH0_FILE_SUCCESS", "_TEST_UDEV_RULES_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE", "_TEST_GRUB_VERIFICATION_SUCCESS")
        }
        elseif ($detectedDistro -imatch "REDHAT") {
            $matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_NETWORK_MANAGER_NOT_INSTALLED","_TEST_NETWORK_FILE_SUCCESS", "_TEST_IFCFG_ETH0_FILE_SUCCESS", "_TEST_UDEV_RULES_SUCCESS", "_TEST_GRUB_VERIFICATION_SUCCESS","_TEST_RHUIREPOSITORIES_AVAILABLE")
        }
        elseif ($detectedDistro -imatch "FEDORA") {
            $matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_NETWORK_MANAGER_NOT_INSTALLED","_TEST_NETWORK_FILE_SUCCESS", "_TEST_IFCFG_ETH0_FILE_SUCCESS", "_TEST_UDEV_RULES_SUCCESS", "_TEST_GRUB_VERIFICATION_SUCCESS")
        }
        elseif ($detectedDistro -imatch "SLES") {
            $matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_GRUB_VERIFICATION_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE")
            # to avoid extra blank space
            $detectedDistro="SLES"
        }
        if ($detectedDistro -imatch "COREOS") {
            $matchstrings = @("_TEST_UDEV_RULES_SUCCESS")
        }

        Copy-RemoteFiles -uploadTo $AllVMData.PublicIP -port $AllVMData.SSHPort -files $currentTestData.files -username $user -password $password -upload
        Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "chmod +x *.py" -runAsSudo | Out-Null

        Write-LogInfo "Executing : ${testScript}"
        $consoleOut = Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "python ${testScript} -d $detectedDistro" -runAsSudo
        Run-LinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "mv Runtime.log ${testScript}.log" -runAsSudo | Out-Null
        Copy-RemoteFiles -download -downloadFrom $AllVMData.PublicIP -files "/home/$user/${testScript}.log" -downloadTo $LogDir -port $AllVMData.SSHPort -username $user -password $password
        $errorCount = 0
        foreach ($testString in $matchstrings) {
            if( $consoleOut -imatch $testString) {
                Write-LogInfo "$detectedDistro$testString"
            } else {
                Write-LogErr "Expected String : $detectedDistro$testString not present. Please check logs."
                $errorCount += 1
            }
        }
        if($errorCount -eq 0) {
            $testResult = "PASS"
        } else {
            $testResult = "FAIL"
        }
        Write-LogInfo "Test Status : Completed"
        Write-LogInfo "Test Resullt : $testResult"
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -AllVMData $AllVmData -CurrentTestData $CurrentTestData
