# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([object] $AllVmData, [object] $CurrentTestData, [object] $TestProvider)

function Main {
	param([object] $allVMData, [object] $CurrentTestData, [object] $TestProvider)
	try {
		$CurrentTestResult = Create-TestResultObject
		$CurrentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "FirstBoot" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
		Write-LogInfo "Check 1: Checking call tracess again after 30 seconds sleep"
		Start-Sleep 30
		$noIssues = Check-KernelLogs -allVMData $allVMData
		if ($noIssues) {
			$CurrentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "FirstBoot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
			$RestartStatus = $TestProvider.RestartAllDeployments($allVMData)
			if($RestartStatus -eq "True") {
				$CurrentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "Reboot" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
				Write-LogInfo "Check 2: Checking call tracess again after Reboot > 30 seconds sleep"
				Start-Sleep 30
				$noIssues = Check-KernelLogs -allVMData $allVMData
				if ($noIssues) {
					$CurrentTestResult.TestSummary += New-ResultSummary -testResult "PASS" -metaData "Reboot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
					Write-LogInfo "Test Result : PASS."
					$testResult = "PASS"
				}
				else {
					$CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "Reboot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
					Write-LogInfo "Test Result : FAIL."
					$testResult = "FAIL"
				}
			}
			else {
				$CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "Reboot" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
				Write-LogInfo "Test Result : FAIL."
				$testResult = "FAIL"
			}

		}
		else {
			$CurrentTestResult.TestSummary += New-ResultSummary -testResult "FAIL" -metaData "FirstBoot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
			Write-LogInfo "Test Result : FAIL."
			$testResult = "FAIL"
		}
	}
	catch {
		$ErrorMessage =  $_.Exception.Message
		Write-LogInfo "EXCEPTION : $ErrorMessage"
	}
	Finally {
		if (!$testResult) {
			$testResult = "Aborted"
		}
		$resultArr += $testResult
	}

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main -allVMData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider
