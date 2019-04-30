# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([object] $AllVmData, [object] $CurrentTestData, [object] $TestProvider)

function Main {
	param([object] $allVMData, [object] $CurrentTestData, [object] $TestProvider)
	try {
		$CurrentTestResult = Create-TestResultObject
		$counter = 1
		Write-LogInfo "Your VMs are ready to use..."
        $azureConfig = $Global:GlobalConfig.Global.Azure
        $subID = $azureConfig.Subscription.SubscriptionID
        $subID = $subID.Trim()
        $ResourceGroup = $allVMData[0].ResourceGroupName
        $currentTestResult.TestSummary +=  New-ResultSummary -testResult "$ResourceGroup" -metaData "Resource Group" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        $currentTestResult.TestSummary +=  New-ResultSummary -testResult "https://ms.portal.azure.com/#resource/subscriptions/$subID/resourceGroups/$ResourceGroup/overview" -metaData "WebURL" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        foreach ( $vm in $allVMData )
        {
            if ( $vm.SSHPort -gt 0 )
            {
                Write-LogInfo "VM #$counter`: $($vm.PublicIP):$($vm.SSHPort)"
                $currentTestResult.TestSummary +=  New-ResultSummary -testResult "$($vm.Status)" -metaData "VM #$counter` : $($vm.PublicIP) : $($vm.SSHPort) " -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                $currentTestResult.TestSummary +=  New-ResultSummary -testResult "ssh $($user)@$($vm.PublicIP) -p $($vm.SSHPort)" -metaData "VM #$counter` : $($vm.RoleName) Connection String" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            }
            elseif($vm.RDPPort -gt 0)
            {
                Write-LogInfo "VM #$counter`: $($vm.PublicIP):$($vm.RDPPort)"
                $currentTestResult.TestSummary +=  New-ResultSummary -testResult "$($vm.Status)" -metaData "VM #$counter` : $($vm.PublicIP) : $($vm.RDPPort) " -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
                $currentTestResult.TestSummary +=  New-ResultSummary -testResult "RDP $($user)@$($vm.PublicIP):$($vm.RDPPort)" -metaData "VM #$counter` : $($vm.RoleName) Connection String" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
            }
            $counter++
        }
		Write-LogInfo "Test Result : PASS."
		$testResult = "PASS"
	} catch {
		$ErrorMessage =  $_.Exception.Message
		Write-LogInfo "EXCEPTION : $ErrorMessage"
	}
	Finally {
		if (!$testResult) {
			$testResult = "Aborted"
		}
		$resultArr += $testResult
	}

	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult
}

Main -allVMData $AllVmData -CurrentTestData $CurrentTestData -TestProvider $TestProvider
