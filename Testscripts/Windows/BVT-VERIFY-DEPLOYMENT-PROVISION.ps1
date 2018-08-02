# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
	try {
		$CurrentTestResult.TestSummary += CreateResultSummary -testResult "PASS" -metaData "FirstBoot" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
		LogMsg "Check 1: Checking call tracess again after 30 seconds sleep"
		Start-Sleep 30
		$noIssues = CheckKernelLogs -allVMData $allVMData
		if ($noIssues) {
			$CurrentTestResult.TestSummary += CreateResultSummary -testResult "PASS" -metaData "FirstBoot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
			$RestartStatus = RestartAllDeployments -allVMData $allVMData
			if($RestartStatus -eq "True") {
				$CurrentTestResult.TestSummary += CreateResultSummary -testResult "PASS" -metaData "Reboot" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
				LogMsg "Check 2: Checking call tracess again after Reboot > 30 seconds sleep"
				Start-Sleep 30
				$noIssues = CheckKernelLogs -allVMData $allVMData
				if ($noIssues) {
					$CurrentTestResult.TestSummary += CreateResultSummary -testResult "PASS" -metaData "Reboot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
					LogMsg "Test Result : PASS."
					$testResult = "PASS"
				}
				else {
					$CurrentTestResult.TestSummary += CreateResultSummary -testResult "FAIL" -metaData "Reboot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
					LogMsg "Test Result : FAIL."
					$testResult = "FAIL"
				}
			}
			else {
				$CurrentTestResult.TestSummary += CreateResultSummary -testResult "FAIL" -metaData "Reboot" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
				LogMsg "Test Result : FAIL."
				$testResult = "FAIL"
			}

		}
		else {
			$CurrentTestResult.TestSummary += CreateResultSummary -testResult "FAIL" -metaData "FirstBoot : Call Trace Verification" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
			LogMsg "Test Result : FAIL."
			$testResult = "FAIL"
		}
	}
	catch {
		$ErrorMessage =  $_.Exception.Message
		LogMsg "EXCEPTION : $ErrorMessage"
	}
	Finally {
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
