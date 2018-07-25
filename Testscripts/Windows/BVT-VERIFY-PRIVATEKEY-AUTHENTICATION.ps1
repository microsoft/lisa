# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
$result = ""
$CurrentTestResult = CreateTestResultObject
$resultArr = @()
$isDeployed = DeployVMS -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
#$isDeployed = "ICA-BVTDeployment-UbuntuCAPT-6-25-5-8-21"
if ($isDeployed)
{

	try
	{
		$testServiceData = Get-AzureService -ServiceName $isDeployed

#Get VMs deployed in the service..
		$testVMsinService = $testServiceData | Get-AzureVM

		$hs1vm1 = $testVMsinService
		$hs1vm1Endpoints = $hs1vm1 | Get-AzureEndpoint
		$hs1vm1sshport = GetPort -Endpoints $hs1vm1Endpoints -usage ssh
		$hs1VIP = $hs1vm1Endpoints[0].Vip
		$hs1ServiceUrl = $hs1vm1.DNSName
		$hs1ServiceUrl = $hs1ServiceUrl.Replace("http://","")
		$hs1ServiceUrl = $hs1ServiceUrl.Replace("/","")
		$hs1vm1Hostname =  $hs1vm1.Name
        LogMsg "Uploading $testFile to $uploadTo, port $port using PrivateKey authentication"
        $successCount = 0
        for ($i = 0; $i -lt 16; $i++)
        {
            try
            {
                LogMsg "Privatekey Authentication Verification loop : $i : STARTED"
                Set-Content -Value "PrivateKey Test" -Path "$logDir\test-file-$i.txt" | Out-Null
                RemoteCopy -uploadTo $hs1VIP -port $hs1vm1sshport -username $user -password $password -files "$logDir\test-file-$i.txt" -upload -usePrivateKey
                Remove-Item -Path "$logDir\test-file-$i.txt" | Out-Null
                RemoteCopy -downloadFrom $hs1VIP -port $hs1vm1sshport -username $user -password $password -downloadTo $logDir -files "/home/$user/test-file-$i.txt" -download -usePrivateKey
                LogMsg "Privatekey Authentication Verification loop : $i : SuCCESS"
                $successCount += 1
            }
            catch
            {
                $testResult = "FAIL"
                LogMsg "Privatekey Authentication Verification loop : $i : FAILED"
            }
        }
        if ($successCount -eq $i)
        {
            $testResult = "PASS"
        }
        else
        {
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
DoTestCleanUp -CurrentTestResult $CurrentTestResult -testName $currentTestData.testName -deployedServices $isDeployed

#Return the result and summery to the test suite script..
return $CurrentTestResult
