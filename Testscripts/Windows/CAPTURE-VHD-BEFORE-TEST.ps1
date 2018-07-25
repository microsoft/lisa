# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#This is not a test. This script will capture the VHD.

$result = ""
$CurrentTestResult = CreateTestResultObject
$resultArr = @()
$isDeployed = DeployVMS -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
if ($isDeployed)
{
    try
    {
        $testResult = $null
        $CaptureVMData = $allVMData
        #region CONFIGURE VM FOR N SERIES GPU TEST
        LogMsg "Test VM details :"
        LogMsg "  RoleName : $($CaptureVMData.RoleName)"
        LogMsg "  Public IP : $($CaptureVMData.PublicIP)"
        LogMsg "  SSH Port : $($CaptureVMData.SSHPort)"
        #endregion
        #region Deprovision the VM.
        LogMsg "Deprovisioning $($CaptureVMData.RoleName)"
        $testJob = RunLinuxCmd -ip $CaptureVMData.PublicIP -port $CaptureVMData.SSHPort -username $user -password $password -command "waagent -deprovision --force" -runAsSudo
        LogMsg "Deprovisioning done."
        #endregion
        LogMsg "Shutting down VM.."
        $stopVM = Stop-AzureRmVM -Name $CaptureVMData.RoleName -ResourceGroupName $CaptureVMData.ResourceGroupName -Force -Verbose
        LogMsg "Shutdown successful."
        #Copy the OS VHD with different name.
        if ($ARMImage)
        {
            $newVHDName = "EOSG-AUTOBUILT-$($ARMImage.Publisher)-$($ARMImage.Offer)-$($ARMImage.Sku)-$($ARMImage.Version)-$Distro"
        }
        if ($OsVHD)
        {
            $newVHDName = "EOSG-AUTOBUILT-$($OsVHD.Replace('.vhd',''))-$Distro"
        }
        $newVHDName = "$newVHDName.vhd"
        LogMsg "Sleeping 30 seconds..."
        Start-Sleep -Seconds 30

        #Collect current VHD, Storage Account and Key
        LogMsg "---------------Copy #1: START----------------"
        $saInfoCollected = $false
        $retryCount = 0
        $maxRetryCount = 999
        while(!$saInfoCollected -and ($retryCount -lt $maxRetryCount))
        {
            try
            {
                $retryCount += 1
                LogMsg "[Attempt $retryCount/$maxRetryCount] : Getting Storage Account details ..."
                $GetAzureRMStorageAccount = $null
                $GetAzureRMStorageAccount = Get-AzureRmStorageAccount
                if ($GetAzureRMStorageAccount -eq $null)
                {
                    throw
                }
                $saInfoCollected = $true
            }
            catch
            {
                LogErr "Error in fetching Storage Account info. Retrying in 10 seconds."
                sleep -Seconds 10
            }
        }
        LogMsg "Collecting OS Disk VHD information."
        $OSDiskVHD = (Get-AzureRmVM -ResourceGroupName $CaptureVMData.ResourceGroupName -Name $CaptureVMData.RoleName).StorageProfile.OsDisk.Vhd.Uri
        $currentVHDName = $OSDiskVHD.Trim().Split("/")[($OSDiskVHD.Trim().Split("/").Count -1)]
        $testStorageAccount = $OSDiskVHD.Replace("http://","").Replace("https://","").Trim().Split(".")[0]
        $sourceRegion = $(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$testStorageAccount"}).Location)
        $targetStorageAccountType =  [string]($(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$testStorageAccount"}).Sku.Tier))
        LogMsg "Check 1: $targetStorageAccountType"
        LogMsg ".\Utilities\CopyVHDtoOtherStorageAccount.ps1 -sourceLocation $sourceRegion -destinationLocations $sourceRegion -destinationAccountType $targetStorageAccountType -sourceVHDName $currentVHDName -destinationVHDName $newVHDName"
        $Out = .\Utilities\CopyVHDtoOtherStorageAccount.ps1 -sourceLocation $sourceRegion -destinationLocations $sourceRegion -destinationAccountType $targetStorageAccountType -sourceVHDName $currentVHDName -destinationVHDName $newVHDName
        LogMsg "---------------Copy #1: END----------------"
        LogMsg "Saving '$newVHDName' to .\CapturedVHD.azure.env"
        $Out = Set-Content -Path .\CapturedVHD.azure.env -Value $newVHDName -NoNewline -Force
        #endregion

        $testResult = "PASS"
    }
    catch
    {
        $ErrorMessage =  $_.Exception.Message
        LogMsg "EXCEPTION : $ErrorMessage"
    }
    Finally
    {
        $metaData = "GPU Verification"
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
DoTestCleanUp -CurrentTestResult $CurrentTestResult -testName $currentTestData.testName -ResourceGroups $isDeployed -SkipVerifyKernelLogs

#Return the result and summery to the test suite script..
return $CurrentTestResult