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
		RemoteCopy -uploadTo $AllVMData.PublicIP -port $AllVMData.SSHPort -files $currentTestData.files -username $user -password $password -upload
		$out = RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "chmod +x *" -runAsSudo

		LogMsg "Executing : $($currentTestData.testScript)"
		RunLinuxCmd -username $user -password $password -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -command "bash -c ./$($currentTestData.testScript)" -runAsSudo
		RemoteCopy -download -downloadFrom $AllVMData.PublicIP -files "/home/$user/TestState.log, /home/$user/TestExecution.log" -downloadTo $LogDir -port $AllVMData.SSHPort -username $user -password $password
		$testResult = Get-Content $LogDir\TestState.log
		LogMsg (Get-Content -Path "$LogDir\TestExecution.log")
		
		LogMsg "Test result : $testResult"
		if ($testResult -eq "PASS")
		{
			LogMsg "Test PASS"
		}
		else
		{
			LogMsg "Test Failed"
		}
	}

	catch
	{
		$ErrorMessage =  $_.Exception.Message
		LogMsg "EXCEPTION : $ErrorMessage"   
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
	$testResult = "Aborted"
	$resultArr += $testResult
}

$CurrentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr

#Clean up the setup
DoTestCleanUp -CurrentTestResult $CurrentTestResult -testName $currentTestData.testName -ResourceGroups $isDeployed

#Return the result and summery to the test suite script..
return $CurrentTestResult