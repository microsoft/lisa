# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        $testServiceData = Get-AzureService -ServiceName $isDeployed
        $testVMsinService = $testServiceData | Get-AzureVM

        $hs1vm1 = $testVMsinService
        $hs1vm1Endpoints = $hs1vm1 | Get-AzureEndpoint
        $hs1vm1sshport = GetPort -Endpoints $hs1vm1Endpoints -usage ssh
        $hs1VIP = $hs1vm1Endpoints[0].Vip
        $hs1ServiceUrl = $hs1vm1.DNSName
        $hs1ServiceUrl = $hs1ServiceUrl.Replace("http://","")
        $hs1ServiceUrl = $hs1ServiceUrl.Replace("/","")
        Write-LogInfo "Uploading $testFile to $uploadTo, port $port using PrivateKey authentication"
        $successCount = 0
        for ($i = 0; $i -lt 16; $i++) {
            try {
                Write-LogInfo "Privatekey Authentication Verification loop : $i : STARTED"
                Set-Content -Value "PrivateKey Test" -Path "$logDir\test-file-$i.txt" | Out-Null
                Copy-RemoteFiles -uploadTo $hs1VIP -port $hs1vm1sshport -username $user -password $password -files "$logDir\test-file-$i.txt" -upload -usePrivateKey
                Remove-Item -Path "$logDir\test-file-$i.txt" | Out-Null
                Copy-RemoteFiles -downloadFrom $hs1VIP -port $hs1vm1sshport -username $user -password $password -downloadTo $logDir -files "/home/$user/test-file-$i.txt" -download -usePrivateKey
                Write-LogInfo "Privatekey Authentication Verification loop : $i : SuCCESS"
                $successCount += 1
            } catch {
                $testResult = "FAIL"
                Write-LogInfo "Privatekey Authentication Verification loop : $i : FAILED"
            }
        }

        if ($successCount -eq $i) {
            $testResult = "PASS"
        } else {
            $testResult = "FAIL"
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

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main
