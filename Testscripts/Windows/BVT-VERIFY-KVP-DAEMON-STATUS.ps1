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

		[string] $rgName = $allVMData.ResourceGroupName
		$hs1VIP = $AllVMData.PublicIP
		$hs1vm1sshport = $AllVMData.SSHPort
		$hs1ServiceUrl = $AllVMData.URL
		$hs1vm1Dip = $AllVMData.InternalIP
		$instanceSize = $allVMData.InstanceSize
		
		ProvisionVMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
	
		#REGION FOR CHECK KVP DAEMON STATUS
		LogMsg "Executing : $($currentTestData.testScriptPs1)"
		Set-Content -Value "**************$($currentTestData.testName)******************" -Path "$logDir\$($currentTestData.testName)_Log.txt"
		LogMsg "Verifcation of KVP Daemon status is started.."
		$kvpStatus = RunLinuxCmd -username "root" -password $password -ip $hs1VIP -port $hs1vm1sshport -command "pgrep -lf 'hypervkvpd|hv_kvp_daemon'" 
		Add-Content -Value "KVP Daemon Status : $kvpStatus " -Path "$logDir\$($currentTestData.testName)_Log.txt"
		if($kvpStatus -imatch "kvp")
		{
			LogMsg "KVP daemon is present in remote VM and KVP DAEMON STATUS : $kvpStatus"
			$testResult = "PASS"
		}
		else 
		{
			LogMsg "KVP daemon is NOT present in remote VM and KVP DAEMON STATUS : $kvpStatus"
			$testResult = "FAIL"
		}
		LogMsg "***********************KVP DAEMON STATUS ***********************"
		LogMsg " KVP DAEMON STATUS: $kvpStatus"	
		LogMsg "******************************************************"
		LogMsg "Test result : $testResult"
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