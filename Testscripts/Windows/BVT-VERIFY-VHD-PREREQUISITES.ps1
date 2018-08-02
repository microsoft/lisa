# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result 
    $result = ""
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try {
        $testScript = "BVT-VERIFY-VHD-PREREQUISITES.py"

        $detectedDistro = DetectLinuxDistro -VIP $AllVMData.PublicIP -SSHport $AllVMData.SSHPort -testVMUser $user -testVMPassword $password
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
        }
        if ($detectedDistro -imatch "COREOS") {
            $matchstrings = @("_TEST_UDEV_RULES_SUCCESS")
        }
      
        RemoteCopy -uploadTo $AllVMData.PublicIP -port $AllVMData.SSHPort -files $currentTestData.files -username $user -password $password -upload
        RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "chmod +x *.py" -runAsSudo

        LogMsg "Executing : ${testScript}"
        $consoleOut = RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "$python_cmd ${testScript} -d $detectedDistro" -runAsSudo
        RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "mv Runtime.log ${testScript}.log" -runAsSudo
        RemoteCopy -download -downloadFrom $AllVMData.PublicIP -files "/home/$user/${testScript}.log" -downloadTo $LogDir -port $AllVMData.SSHPort -username $user -password $password
        $errorCount = 0
        foreach ($testString in $matchstrings) {
            if( $consoleOut -imatch $testString) {
                LogMsg "$detectedDistro$testString"
            } else {
                LogErr "Expected String : $detectedDistro$testString not present. Please check logs."
                $errorCount += 1
            }
        }  
        if($errorCount -eq 0) {
            $testResult = "PASS"
        } else {
            $testResult = "FAIL"
        }
        LogMsg "Test Status : Completed"
        Logmsg "Test Resullt : $testResult"
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogMsg "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        $metaData = ""
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult  
}

Main
