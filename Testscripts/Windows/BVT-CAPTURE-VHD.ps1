# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

try {
    if ($testId.ToUpper() -eq "AZUREBVT_000" -and ($customKernel -or $customLIS)) {   

        $isDeployed = DeployVMS -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
        if ($isDeployed) {
            foreach ($VM in $allVMData) {
                $ResourceGroupUnderTest = $VM.ResourceGroupName
                Set-Variable -Name ResourceGroupUnderTest -Value $ResourceGroupUnderTest -Scope Global
                $VHDuri = (Get-AzureRMVM -ResourceGroupName $VM.ResourceGroupName).StorageProfile.OsDisk.Vhd.Uri
                #Deprovision VM
                LogMsg "Executing: waagent -deprovision..."
                $DeprovisionInfo = RunLinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort -command "/usr/sbin/waagent -force -deprovision" -runAsSudo
                LogMsg $DeprovisionInfo
                LogMsg "Execution of waagent -deprovision done successfully"
                LogMsg "Stopping Virtual Machine ...."
                $out = Stop-AzureRmVM -ResourceGroupName $VM.ResourceGroupName -Name $VM.RoleName -Force
                WaitFor -seconds 60
            }
            #get the VHD file name from the VHD uri
            $VHDuri = Split-Path $VHDuri -Leaf
            #set BaseOsVHD so that deployment will pick the VHD
            Set-Variable -Name BaseOsVHD -Value $VHDuri -Scope Global

            #Finally set customKernel and customLIS to null which are not required to be installed after deploying Virtual machine
            $customKernel = $null
            Set-Variable -Name customKernel -Value $customKernel -Scope Global
            $customLIS = $null
            Set-Variable -Name customLIS -Value $customLIS -Scope Global
            $testResult = "PASS"
            $testStatus = "TestCompleted"   
            LogMsg "Resource Group deployed successfully. VHD is captured and it will be used for further tests"
        } else {
            $testResult = "Aborted"
        }
    }
    elseif ($testId.ToUpper() -eq "AZUREBVT_100") {
        if($ResourceGroupUnderTest) {
            $out = DeleteResourceGroup -RGName $ResourceGroupUnderTest
            LogMsg "Captured VHD is deleted along with the associated Resource Group."
        }
        $testResult = "PASS"
        $testStatus = "TestCompleted"   
    } else {
        $testResult = "PASS"
        $testStatus = "TestCompleted"   
        LogMsg "Capture VHD is not required since customLIS or customKernel is not specified. Continue with further tests"
    }
} catch {
    $ErrorMessage =  $_.Exception.Message
    LogMsg "EXCEPTION : $ErrorMessage"      
} finally {
    if (!$testResult) {
        $testResult = "Aborted"
    }
    $resultArr += $testResult
}

$currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr

return $currentTestResult
