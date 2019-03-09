# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
$CurrentTestResult = Create-TestResultObject
$resultArr = @()

$isDeployed = "THIS-IS-DEMO-FAIL"
if ($isDeployed)
{
	try
	{
        Write-LogInfo "Test Result : FAIL."
        $testResult = "FAIL"
	}
	catch
	{
		$ErrorMessage =  $_.Exception.Message
		Write-LogInfo "EXCEPTION : $ErrorMessage"
	}
	Finally
	{
		if (!$testResult)
		{
			$testResult = "Aborted"
		}
		$resultArr += $testResult
	}
}

else
{
	$testResult = "FAIL"
	$resultArr += $testResult
}

$CurrentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr

#Clean up the setup
Do-TestCleanUp -CurrentTestResult $CurrentTestResult -testName $currentTestData.testName -ResourceGroups $isDeployed

#Return the result and summery to the test suite script..
return $CurrentTestResult
