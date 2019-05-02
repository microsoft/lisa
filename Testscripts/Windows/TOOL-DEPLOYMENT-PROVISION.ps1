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
        foreach ($param in $CurrentTestData.TestParameters.param) {
            if ($param -imatch "AutoCleanup") {
                $DeployVMAutoClenaup = $param.Replace("AutoCleanup=","")
            }
        }
        if ($DeployVMAutoClenaup) {
            if ($DeployVMAutoClenaup -imatch "Disabled") {
                $AutoCleanupDate = "Disabled"
                Write-LogWarn "***************************************************************************"
                Write-LogWarn "AutoCleanup Disabled."
                Write-LogWarn "Please make sure that, you delete / deallocate the VM(s), when not in use."
                Write-LogWarn "***************************************************************************"
            } else {
                $DeployVMAutoClenaup = [int]$DeployVMAutoClenaup
                $AutoCleanupDate = (Get-Date).AddDays($DeployVMAutoClenaup).ToString()
                Write-LogInfo "***************************************************************************"
                Write-LogInfo "AutoCleanup scheduled on $AutoCleanupDate."
                Write-LogInfo "To keep your VMs beyond cleanup date, Please add 'CanNotDelete' lock to your resource group."
                Write-LogInfo "***************************************************************************"
            }
            Add-ResourceGroupTag -ResourceGroup $ResourceGroup -TagName AutoCleanup -TagValue $AutoCleanupDate
        } else {
            $AutoCleanupDate = "As per subscription cleanup policy"
            Write-LogWarn "***************************************************************************"
            Write-LogWarn "AutoCleanup parameter is missing."
            Write-LogWarn "Your VMs may get deleted as per subscriptions's cleanup policy."
            Write-LogWarn "***************************************************************************"
        }
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
        $currentTestResult.TestSummary +=  New-ResultSummary -testResult "$AutoCleanupDate" -metaData "Auto Cleanup Resource Group" -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
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
