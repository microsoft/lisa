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
		$DistroName = DetectLinuxDistro -VIP $hs1VIP -SSHport $hs1vm1sshport -testVMUser $user -testVMPassword $password
		if ($DistroName -eq "REDHAT")
		{
			RemoteCopy -uploadTo $hs1VIP -port $hs1vm1sshport -files $currentTestData.files -username $user -password $password -upload
			RunLinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "chmod +x *" -runAsSudo
			LogMsg "Executing : $($currentTestData.testScript)"
			RunLinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "bash $($currentTestData.testScript)" -runAsSudo -runMaxAllowedTime 1800
			RemoteCopy -download -downloadFrom $hs1VIP -files "/home/$user/state.txt, /home/$user/Summary.log, /home/$user/$($currentTestData.testScript).log" -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
			$testResult = Get-Content $LogDir\Summary.log
			$testStatus = Get-Content $LogDir\state.txt
			LogMsg "Test result : $testResult"
		}
		else
		{
			LogMsg "The Distro is not Redhat, skip the test!"
			$testResult = 'PASS'
			$testStatus = 'TestCompleted'
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
