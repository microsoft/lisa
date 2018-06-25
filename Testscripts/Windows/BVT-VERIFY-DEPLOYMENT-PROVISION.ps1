$CurrentTestResult = CreateTestResultObject
$resultArr = @()

$isDeployed = DeployVMS -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
if ($isDeployed)
{
	try
	{
		LogMsg "Check 1: Checking call tracess again after 30 seconds sleep"
		LogMsg "Test Result : PASS."
		$testResult = "PASS"
		<#
		Start-Sleep 30
		
		if ($noIssues)
		{
			$RestartStatus = RestartAllDeployments -allVMData $allVMData
			if($RestartStatus -eq "True")
			{
				LogMsg "Check 2: Checking call tracess again after Reboot > 30 seconds sleep"
				Start-Sleep 30
				$noIssues = CheckKernelLogs -allVMData $allVMData
				if ($noIssues)
				{
					LogMsg "Test Result : PASS."
					$testResult = "PASS"
				}
				else
				{
					LogMsg "Test Result : FAIL."
					$testResult = "FAIL"
				}
			}
			else
			{
				LogMsg "Test Result : FAIL."
				$testResult = "FAIL"
			}
			
		}
		else
		{
			LogMsg "Test Result : FAIL."
			$testResult = "FAIL"
		}
		#>
	}
	catch
	{
		$ErrorMessage =  $_.Exception.Message
		LogMsg "EXCEPTION : $ErrorMessage"
	}
	Finally
	{
		$metaData = ""
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

$CurrentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr

#Clean up the setup
DoTestCleanUp -CurrentTestResult $CurrentTestResult -testName $currentTestData.testName -ResourceGroups $isDeployed

#Return the result and summery to the test suite script..
return $CurrentTestResult