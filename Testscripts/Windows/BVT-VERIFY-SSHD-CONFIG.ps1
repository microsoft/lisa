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

		RemoteCopy -uploadTo $hs1VIP -port $hs1vm1sshport -files $currentTestData.files -username $user -password $password -upload
		RunLinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "chmod +x *" -runAsSudo

		LogMsg "Executing : $($currentTestData.testScript)"
		$output=RunLinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "$python_cmd $($currentTestData.testScript)" -runAsSudo
		RunLinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "mv Runtime.log $($currentTestData.testScript).log" -runAsSudo
		RemoteCopy -download -downloadFrom $hs1VIP -files "/home/$user/state.txt, /home/$user/Summary.log, /home/$user/$($currentTestData.testScript).log" -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
		$testResult = Get-Content $LogDir\Summary.log
		$testStatus = Get-Content $LogDir\state.txt
		LogMsg "Test result : $testResult"
		if ($output -imatch "CLIENT_ALIVE_INTERVAL_SUCCESS")
		{
			LogMsg "SSHD-CONFIG INFO :Client_Alive_Interval time is 180 Second"
		}
		else
		{
			if($output -imatch "CLIENT_ALIVE_INTERVAL_FAIL")
			{
				LogMsg "SSHD-CONFIG INFO :There is no Client_Alive_Interval time is 180 Second"
			}
			if($output -imatch "CLIENT_ALIVE_INTERVAL_COMMENTED")
			{
				LogMsg "SSHD-CONFIG INFO :There is a commented line in CLIENT_INTERVAL_COMMENTED "
			}
		}
		
		if ($testStatus -eq "TestCompleted")
		{
			LogMsg "Test Completed"
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
	$testResult = "Aborted"
	$resultArr += $testResult
}

$CurrentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr

#Clean up the setup
DoTestCleanUp -CurrentTestResult $CurrentTestResult -testName $currentTestData.testName -ResourceGroups $isDeployed

#Return the result and summery to the test suite script..
return $CurrentTestResult
