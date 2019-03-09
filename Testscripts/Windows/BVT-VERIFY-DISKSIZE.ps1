# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
$currentTestResult = Create-TestResultObject
$resultArr = @()

$isDeployed = Deploy-VMs -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
if ($isDeployed) {
    try {
        $hs1VIP = $AllVMData.PublicIP
        $hs1vm1sshport = $AllVMData.SSHPort

        $OsImageSize = Get-AzureVMImage | where {$_.ImageName -eq $BaseOsImage} | % {$_.LogicalSizeInGB}
        $OsImageSizeByte = $OsImageSize*1024*1024*1024

        Copy-RemoteFiles -uploadTo $hs1VIP -port $hs1vm1sshport -files $currentTestData.files -username $user -password $password -upload
        Run-LinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "chmod +x *" -runAsSudo

        Write-LogInfo "Executing : $($currentTestData.testScript)"
        Run-LinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "python $($currentTestData.testScript) -e $OsImageSizeByte" -runAsSudo
        Run-LinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "mv Runtime.log $($currentTestData.testScript).log" -runAsSudo
        Copy-RemoteFiles -download -downloadFrom $hs1VIP -files "/home/$user/state.txt, /home/$user/Summary.log, /home/$user/$($currentTestData.testScript).log" -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
        $testResult = Get-Content $LogDir\Summary.log
        $testStatus = Get-Content $LogDir\state.txt
        Write-LogInfo "Test result : $testResult"

        if ($testStatus -eq "TestCompleted") {
            Write-LogInfo "Test Completed"
        }
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
} else {
    $testResult = "Aborted"
    $resultArr += $testResult
}

$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr

#Clean up the setup
Do-TestCleanUp -currentTestResult $currentTestResult -testName $currentTestData.testName -deployedServices $isDeployed

#Return the result and summery to the test suite script..
return $currentTestResult
