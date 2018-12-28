# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

function Main {
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()

    try {
        $testResult = $null
        $captureVMData = $allVMData
        Write-LogInfo "Test VM details :"
        Write-LogInfo "  RoleName : $($captureVMData.RoleName)"
        Write-LogInfo "  Public IP : $($captureVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($captureVMData.SSHPort)"

        # region Deprovision the VM.
        Write-LogInfo "Deprovisioning $($captureVMData.RoleName)"
        # Note(v-advlad): Running remote commands might not work after deprovision,
        # so we need to detect the distro before deprovisioning
        $detectedDistro = Detect-LinuxDistro -VIP $captureVMData.PublicIP -SSHport $captureVMData.SSHPort `
            -testVMUser $user -testVMPassword $password
        Run-LinuxCmd -ip $captureVMData.PublicIP -port $captureVMData.SSHPort `
            -username $user -password $password -command "waagent -deprovision --force && export HISTSIZE=0" `
            -runAsSudo | Out-Null

        # Note(v-asofro): required for Ubuntu Bionic
        # Similar issue: https://github.com/Azure/WALinuxAgent/issues/1359
        if ($detectedDistro -eq "UBUNTU") {
            try {
                Run-LinuxCmd -ip $captureVMData.PublicIP -port $captureVMData.SSHPort -username $user -password $password `
                    -command " lsb_release --codename | grep bionic && sed -i 's/Provisioning.Enabled=n/Provisioning.Enabled=y/g' /etc/waagent.conf && sed -i 's/Provisioning.UseCloudInit=y/Provisioning.UseCloudInit=n/g' /etc/waagent.conf && touch /etc/cloud/cloud-init.disabled " `
                    -ignoreLinuxExitCode -runAsSudo | Out-Null
            } catch {
                Write-LogInfo "Could not potentially fix Ubuntu Bionic waagent. Continue execution..."
            }
        }
        Write-LogInfo "Deprovisioning done."
        # endregion

        Write-LogInfo "Shutting down VM..."
        $null = Stop-AzureRmVM -Name $captureVMData.RoleName -ResourceGroupName $captureVMData.ResourceGroupName -Force
        Write-LogInfo "VM shutdown successful."
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
        Write-LogInfo "Sleeping 30 seconds..."
        Start-Sleep -Seconds 30

        # Collect current VHD, Storage Account and Key
        Write-LogInfo "---------------Copy #1: START----------------"
        $saInfoCollected = $false
        $retryCount = 0
        $maxRetryCount = 999
        while(!$saInfoCollected -and ($retryCount -lt $maxRetryCount)) {
            try {
                $retryCount += 1
                Write-LogInfo "[Attempt $retryCount/$maxRetryCount] : Getting Storage Account details..."
                $GetAzureRMStorageAccount = $null
                $GetAzureRMStorageAccount = Get-AzureRmStorageAccount
                if (!$GetAzureRMStorageAccount) {
                    throw
                }
                $saInfoCollected = $true
            } catch {
                Write-LogErr "Error in fetching Storage Account info. Retrying in 10 seconds."
                Start-Sleep -Seconds 10
            }
        }
        Write-LogInfo "Collecting OS Disk VHD information."
        $OSDiskVHD = (Get-AzureRmVM -ResourceGroupName $captureVMData.ResourceGroupName -Name $captureVMData.RoleName).StorageProfile.OsDisk.Vhd.Uri
        $currentVHDName = $OSDiskVHD.Trim().Split("/")[($OSDiskVHD.Trim().Split("/").Count -1)]
        $testStorageAccount = $OSDiskVHD.Replace("http://","").Replace("https://","").Trim().Split(".")[0]
        $sourceRegion = $(($GetAzureRmStorageAccount  | Where-Object {$_.StorageAccountName -eq "$testStorageAccount"}).Location)
        $targetStorageAccountType =  [string]($(($GetAzureRmStorageAccount  | Where-Object {$_.StorageAccountName -eq "$testStorageAccount"}).Sku.Tier))
        Write-LogInfo "Check 1: $targetStorageAccountType"
        Write-LogInfo ".\Utilities\CopyVHDtoOtherStorageAccount.ps1 -sourceLocation $sourceRegion -destinationLocations $sourceRegion -destinationAccountType $targetStorageAccountType -sourceVHDName $currentVHDName -destinationVHDName $newVHDName"
        $null = .\Utilities\CopyVHDtoOtherStorageAccount.ps1 -sourceLocation $sourceRegion -destinationLocations $sourceRegion -destinationAccountType $targetStorageAccountType -sourceVHDName $currentVHDName -destinationVHDName $newVHDName
        Write-LogInfo "---------------Copy #1: END----------------"
        Write-LogInfo "Saving '$newVHDName' to .\CapturedVHD.azure.env"
        $null = Set-Content -Path .\CapturedVHD.azure.env -Value $newVHDName -NoNewline -Force
        #endregion

        $testResult = "PASS"
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
