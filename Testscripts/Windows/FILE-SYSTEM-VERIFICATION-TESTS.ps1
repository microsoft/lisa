# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Description:
#     This Powershell script will run xfstesting.sh bash script
#     - It will construct the config file needed by xfstesting.sh
#     - It will start xfstesting.sh. Max allowed run time is 3 hours.
#     - If state.txt is in TestRunning state after 3 hours, it will
#     abort the test.
#######################################################################
param([object] $AllVmData,
      [object] $CurrentTestData
    )

$randomString = -join ((97..122) | Get-Random -Count 8 | ForEach-Object {[char]$_})
$storageAccountName = "templisav2" + $randomString
$fileShareName = "fileshare"
$scratchName = "scratch"
$skuName = "Standard_LRS"

function Remove-StorageAccount {
    param (
        [string] $storageAccountName
    )
    Remove-AzStorageAccount -ResourceGroupName $AllVmData.ResourceGroupName `
        -Name $storageAccountName -Force
}

function New-FileShare {
    param (
        $AllVmData,
        $xfstestsConfig
    )

    # Create a new storage account inside the test RG
    Write-LogInfo "Creating a new storage account"
    $storageAccount = New-AzStorageAccount -ResourceGroupName $AllVmData.ResourceGroupName `
        -Name $storageAccountName -Location $TestLocation -SkuName $skuName -Verbose
    if ($null -eq $storageAccount) {
        Write-LogErr "Failed to create a new storage account"
        Remove-StorageAccount $storageAccountName
        return 1
    }

    # Create file share on the storage account
    $fileShareInfo = New-AzStorageShare -Name $fileShareName -Context $storageAccount.Context -Verbose
    if ($null -eq $fileShareInfo) {
        Write-LogErr "Failed to create a new file share"
        Remove-StorageAccount $storageAccountName
        return 1
    }
    $scratchInfo = New-AzStorageShare -Name $scratchName -Context $storageAccount.Context -Verbose
    if ($null -eq $scratchInfo) {
        Write-LogErr "Failed to create a new file share"
        Remove-StorageAccount $storageAccountName
        return 1
    }
    $sharePassword = (Get-AzStorageAccountKey -ResourceGroupName $AllVmData.ResourceGroupName `
        -Name $storageAccountName).Value[0]
    $shareHost = (Get-AzStorageShare -Context $storageAccount.Context).Uri.Host[0]
    $url_main = $shareHost + "/" + $fileShareName
    $url_scratch = $shareHost + "/" + $scratchName
    Add-Content -Value "TEST_DEV=//$url_main" -Path $xfstestsConfig
    Add-Content -Value "SCRATCH_DEV=//$url_scratch" -Path $xfstestsConfig

    # Add new info in constants.sh
    $cmdToSend = "sed -i '/TEST_FS_MOUNT_OPTS/d' /$superuser/constants.sh; echo 'share_user=`"$storageAccountName`"' >> /$superuser/constants.sh"
    Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
        -password $password -command $cmdToSend | Out-Null
        $cmdToSend = "sed -i '/MOUNT_OPTIONS/d' /$superuser/constants.sh; echo 'share_scratch=`"$url_scratch`"' >> /$superuser/constants.sh"
    Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
        -password $password -command $cmdToSend | Out-Null
    $cmdToSend = "echo 'share_main=`"$url_main`"' >> /$superuser/constants.sh; echo 'share_pass=`"$sharePassword`"' >> /$superuser/constants.sh"
    Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
        -password $password -command $cmdToSend | Out-Null
    $cmdToSend = "echo 'fstab_info=`"nofail,vers=3.0,credentials=/etc/smbcredentials/lisav2.cred,dir_mode=0777,file_mode=0777,serverino`"' >> /$superuser/constants.sh"
    Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
        -password $password -command $cmdToSend | Out-Null

    return 0
}

function Main {
    param (
        $AllVmData,
        $CurrentTestData
    )
    # Create test result
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    $superuser = "root"

    try {
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort `
            -files $currentTestData.files -username $superuser -password $password -upload

        # Construct xfstesting config file
        $xfstestsConfig = Join-Path $env:TEMP "xfstests-config.config"
        Write-LogInfo "Generating $xfstestsConfig..."
        Set-Content -Value "" -Path $xfstestsConfig -NoNewline
        foreach ($param in $currentTestData.TestParameters.param) {
            if ($param -imatch "FSTYP=") {
                $TestFileSystem = ($param.Replace("FSTYP=",""))
                Add-Content -Value "[$TestFileSystem]" -Path $xfstestsConfig
                Write-LogInfo "[$TestFileSystem] added to xfstests-config.config"
            }
            Add-Content -Value "$param" -Path $xfstestsConfig
            Write-LogInfo "$param added to xfstests-config.config"
        }
        if ($TestFileSystem -eq "cifs") {
            $sts = New-FileShare $AllVmData $xfstestsConfig
            if ($sts[-1] -ne 0) {
                throw "Failed to setup cifs"
            }
        }
        Write-LogInfo "$xfstestsConfig created successfully"

        # Start the test script
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort `
            -files $xfstestsConfig -username $superuser -password $password -upload
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
            -password $password -command "/$superuser/xfstesting.sh" -RunInBackground | Out-Null
        # Check the status of the run every minute
        # If the run is longer than 4 hours, abort the test
        $timeout = New-Timespan -Minutes 240
        $sw = [diagnostics.stopwatch]::StartNew()
        while ($sw.elapsed -lt $timeout) {
            Start-Sleep -Seconds 60
            $isVmAlive = Is-VmAlive -AllVMDataObject $allVMData -MaxRetryCount 10
            if ($isVmAlive -eq "True") {
                $state = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort `
                -username $superuser -password $password "cat state.txt"
                if ($state -eq "TestCompleted") {
                    Write-LogInfo "xfstesting.sh finished the run successfully!"
                    break
                } elseif ($state -eq "TestFailed") {
                    Write-LogErr "xfstesting.sh failed on the VM!"
                    break
                } elseif ($state -eq "TestAborted") {
                    Write-LogErr "xfstesting.sh aborted on the VM!"
                    break
                } elseif ($state -eq "TestSkipped") {
                    Write-LogWarn "xfstesting.sh skipped on the VM!"
                    break
                }
                Write-LogInfo "xfstesting.sh is still running!"
            } else {
                throw "VM is not responding during testing."
            }
        }

        # Get logs. An extra check for the previous $state is needed
        # The test could actually hang. If state.txt is showing
        # 'TestRunning' then abort the test
        #####
        # We first need to move copy from root folder to user folder for
        # Collect-TestLogs function to work
        Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $superuser `
            -password $password -command "cp * /home/$user" -ignoreLinuxExitCode:$true | Out-Null
        $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName `
            $currentTestData.files.Split('\')[3].Split('.')[0] -TestType "sh"  -PublicIP `
            $allVMData.PublicIP -SSHPort $allVMData.SSHPort -Username $user `
            -password $password -TestName $currentTestData.testName
        if ($state -eq "TestRunning") {
            $resultArr += "ABORTED"
            Write-LogErr "xfstesting.sh is still running after 4 hours!"
        } else {
            $resultArr += $testResult
        }

        Write-LogInfo "Test Completed."
        Write-LogInfo "Test Result: $testResult"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION: $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData
