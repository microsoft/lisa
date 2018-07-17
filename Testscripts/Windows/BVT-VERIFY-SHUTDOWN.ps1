# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
$result = ""
$CurrentTestResult = CreateTestResultObject
$resultArr = @()

$isDeployed = DeployVMS -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
if ($isDeployed)
{
	try
	{
		$hs1VIP = $AllVMData.PublicIP
		$hs1vm1sshport = $AllVMData.SSHPort
		$hs1ServiceUrl = $AllVMData.URL
		$hs1vm1Dip = $AllVMData.InternalIP
		LogMsg "Trying to shut down $($AllVMData.RoleName)..."
		if ( $UseAzureResourceManager )
		{
			$stopVM = Stop-AzureRmVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName -Force -StayProvisioned -Verbose
			if ( $? )
			{
				$isStopped = $true
			}
			else
			{
				$isStopped = $false
			}
		}
		else
		{
			$out = StopAllDeployments -DeployedServices $isDeployed
			$isStopped = $?
		}
		if ($isStopped)
		{
			LogMsg "Virtual machine shut down successful."
			$testResult = "PASS"
		}
		else
		{
			LogErr "Virtual machine shut down failed."
			$testResult = "FAIL"
		}
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
DoTestCleanUp -CurrentTestResult $CurrentTestResult -testName $currentTestData.testName -ResourceGroups $isDeployed -SkipVerifyKernelLogs

#Return the result and summery to the test suite script..
return $CurrentTestResult
