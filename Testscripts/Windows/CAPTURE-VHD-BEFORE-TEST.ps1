# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData)

function Main {
    param([object] $AllVMData)
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
        Run-LinuxCmd -ip $captureVMData.PublicIP -port $captureVMData.SSHPort `
            -username $user -password $password -command "waagent -deprovision --force && export HISTSIZE=0" `
            -runAsSudo | Out-Null
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
        if ($global:ARMImageName) {
            $ARMImage = $global:ARMImageName.Split(" ")
            $newVHDName = "EOSG-AUTOBUILT-$($ARMImage[0])-$($ARMImage[1])-$($ARMImage[2])-$($ARMImage[3])-$Append"
        }
        if ($global:BaseOsVHD) {
            $OSVhd = $global:BaseOsVHD.Split('/')[-1]
            $newVHDName = "EOSG-AUTOBUILT-$($OSVhd.Replace('.vhd',''))-$Append"
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

Main -AllVMData $AllVmData
