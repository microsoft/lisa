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

		$detectedDistro = DetectLinuxDistro -VIP $hs1VIP -SSHport $hs1vm1sshport -testVMUser $user -testVMPassword $password
		if ($detectedDistro -imatch "UBUNTU")
		{
			$matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_GRUB_VERIFICATION_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE")
		}
		if ($detectedDistro -imatch "DEBIAN")
		{
			$matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE")
		}
		elseif ($detectedDistro -imatch "SUSE")
		{
			$matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_GRUB_VERIFICATION_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE")
		}
		elseif ($detectedDistro -imatch "CENTOS")
		{
			$matchstrings = @("_TEST_NETWORK_MANAGER_NOT_INSTALLED","_TEST_NETWORK_FILE_SUCCESS", "_TEST_IFCFG_ETH0_FILE_SUCCESS", "_TEST_UDEV_RULES_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE", "_TEST_GRUB_VERIFICATION_SUCCESS")
		}
		elseif ($detectedDistro -imatch "ORACLELINUX")
		{
			$matchstrings = @("_TEST_NETWORK_MANAGER_NOT_INSTALLED","_TEST_NETWORK_FILE_SUCCESS", "_TEST_IFCFG_ETH0_FILE_SUCCESS", "_TEST_UDEV_RULES_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE", "_TEST_GRUB_VERIFICATION_SUCCESS")
		}
		elseif ($detectedDistro -imatch "REDHAT")
		{
			$matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_NETWORK_MANAGER_NOT_INSTALLED","_TEST_NETWORK_FILE_SUCCESS", "_TEST_IFCFG_ETH0_FILE_SUCCESS", "_TEST_UDEV_RULES_SUCCESS", "_TEST_GRUB_VERIFICATION_SUCCESS","_TEST_RHUIREPOSITORIES_AVAILABLE")
		}
		elseif ($detectedDistro -imatch "FEDORA")
		{	
			$matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_NETWORK_MANAGER_NOT_INSTALLED","_TEST_NETWORK_FILE_SUCCESS", "_TEST_IFCFG_ETH0_FILE_SUCCESS", "_TEST_UDEV_RULES_SUCCESS", "_TEST_GRUB_VERIFICATION_SUCCESS")
		}
		elseif ($detectedDistro -imatch "SLES")
		{
			$matchstrings = @("_TEST_SUDOERS_VERIFICATION_SUCCESS","_TEST_GRUB_VERIFICATION_SUCCESS", "_TEST_REPOSITORIES_AVAILABLE")
		}
		if ($detectedDistro -imatch "COREOS")
		{
			$matchstrings = @("_TEST_UDEV_RULES_SUCCESS")
		}
	  
		RemoteCopy -uploadTo $hs1VIP -port $hs1vm1sshport -files $currentTestData.files -username $user -password $password -upload
		RunLinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "chmod +x *.py" -runAsSudo


		LogMsg "Executing : $($currentTestData.testScript)"
		$consoleOut = RunLinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "$python_cmd $($currentTestData.testScript) -d $detectedDistro" -runAsSudo
		RunLinuxCmd -username $user -password $password -ip $hs1VIP -port $hs1vm1sshport -command "mv Runtime.log $($currentTestData.testScript).log" -runAsSudo
		RemoteCopy -download -downloadFrom $hs1VIP -files "/home/$user/$($currentTestData.testScript).log" -downloadTo $LogDir -port $hs1vm1sshport -username $user -password $password
		$errorCount = 0
		foreach ($testString in $matchstrings)
		{
			if( $consoleOut -imatch $testString)
			{
				LogMsg "$detectedDistro$testString"
			}
			else
			{
				LogErr "Expected String : $detectedDistro$testString not present. Please check logs."
				$errorCount += 1
			}
		}  
		if($errorCount -eq 0)
		{
			$testResult = "PASS"
		}
		else
		{
			$testResult = "FAIL"
		}
		LogMsg "Test Status : Completed"
		Logmsg "Test Resullt : $testResult"
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