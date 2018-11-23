# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result
    $currentTestResult = CreateTestResultObject
    $resultArr = @()

    try {
        $testResult = $null
        $captureVMData = $allVMData
        # region CONFIGURE VM FOR N SERIES GPU TEST
        LogMsg "Test VM details:"
        LogMsg "    RoleName: $($captureVMData.RoleName)"
        LogMsg "    Public IP: $($captureVMData.PublicIP)"
        LogMsg "    SSH Port: $($captureVMData.SSHPort)"
        # endregion

        # region Deprovision the VM.
        LogMsg "Deprovisioning $($captureVMData.RoleName)"
        # Note(v-advlad): Running remote commands might not work after deprovision,
        # so we need to detect the distro vefore deprovisioning
        $detectedDistro = DetectLinuxDistro -VIP $captureVMData.PublicIP -SSHport $captureVMData.SSHPort `
            -testVMUser $user -testVMPassword $password
        RunLinuxCmd -ip $captureVMData.PublicIP -port $captureVMData.SSHPort `
            -username $user -password $password -command "waagent -deprovision --force" `
            -runAsSudo | Out-Null

        # Note(v-asofro): required for Ubuntu Bionic
        # Similar issue: https://github.com/Azure/WALinuxAgent/issues/1359
        if ($detectedDistro -eq "UBUNTU") {
            try {
                RunLinuxCmd -ip $captureVMData.PublicIP -port $captureVMData.SSHPort -username $user -password $password `
                    -command " lsb_release --codename | grep bionic && sed -i 's/Provisioning.Enabled=n/Provisioning.Enabled=y/g' /etc/waagent.conf | sed -i 's/Provisioning.UseCloudInit=y/Provisioning.UseCloudInit=n/g' /etc/waagent.conf " `
                    -ignoreLinuxExitCode -runAsSudo | Out-Null
            } catch {
                LogInfo "Could not potentialy fix Ubuntu Bionic waagent. Continue execution..."
            }
        }
        LogMsg "Deprovisioning done."
        # endregion

        LogMsg "Shutting down VM.."
        $null = Stop-AzureRmVM -Name $captureVMData.RoleName -ResourceGroupName $captureVMData.ResourceGroupName -Force -Verbose
        LogMsg "Shutdown successful."
        $Append = $Distro
        if ($env:BUILD_NAME){
            $Append += "-$env:BUILD_NAME"
        }
        if ($env:BUILD_NUMBER){
            $Append += "-$env:BUILD_NUMBER"
        }
        #Copy the OS VHD with different name.
        if ($ARMImage) {
            $newVHDName = "EOSG-AUTOBUILT-$($ARMImage.Publisher)-$($ARMImage.Offer)-$($ARMImage.Sku)-$($ARMImage.Version)-$Append"
        }
        if ($OsVHD) {
            $newVHDName = "EOSG-AUTOBUILT-$($OsVHD.Replace('.vhd',''))-$Append"
        }
        $newVHDName = "$newVHDName.vhd"
        LogMsg "Sleeping 30 seconds..."
        Start-Sleep -Seconds 30

        #Collect current VHD, Storage Account and Key
        LogMsg "---------------Copy #1: START----------------"
        $saInfoCollected = $false
        $retryCount = 0
        $maxRetryCount = 999
        while(!$saInfoCollected -and ($retryCount -lt $maxRetryCount)) {
            try {
                $retryCount += 1
                LogMsg "[Attempt $retryCount/$maxRetryCount] : Getting Storage Account details ..."
                $GetAzureRMStorageAccount = $null
                $GetAzureRMStorageAccount = Get-AzureRmStorageAccount
                if ($GetAzureRMStorageAccount -eq $null) {
                    throw
                }
                $saInfoCollected = $true
            } catch {
                LogErr "Error in fetching Storage Account info. Retrying in 10 seconds."
                sleep -Seconds 10
            }
        }
        LogMsg "Collecting OS Disk VHD information."
        $OSDiskVHD = (Get-AzureRmVM -ResourceGroupName $captureVMData.ResourceGroupName -Name $captureVMData.RoleName).StorageProfile.OsDisk.Vhd.Uri
        $currentVHDName = $OSDiskVHD.Trim().Split("/")[($OSDiskVHD.Trim().Split("/").Count -1)]
        $testStorageAccount = $OSDiskVHD.Replace("http://","").Replace("https://","").Trim().Split(".")[0]
        $sourceRegion = $(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$testStorageAccount"}).Location)
        $targetStorageAccountType =  [string]($(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$testStorageAccount"}).Sku.Tier))
        LogMsg "Check 1: $targetStorageAccountType"
        LogMsg ".\Utilities\CopyVHDtoOtherStorageAccount.ps1 -sourceLocation $sourceRegion -destinationLocations $sourceRegion -destinationAccountType $targetStorageAccountType -sourceVHDName $currentVHDName -destinationVHDName $newVHDName"
        $null = .\Utilities\CopyVHDtoOtherStorageAccount.ps1 -sourceLocation $sourceRegion -destinationLocations $sourceRegion -destinationAccountType $targetStorageAccountType -sourceVHDName $currentVHDName -destinationVHDName $newVHDName
        LogMsg "---------------Copy #1: END----------------"
        LogMsg "Saving '$newVHDName' to .\CapturedVHD.azure.env"
        $null = Set-Content -Path .\CapturedVHD.azure.env -Value $newVHDName -NoNewline -Force
        #endregion

        $testResult = "PASS"
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogMsg "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
