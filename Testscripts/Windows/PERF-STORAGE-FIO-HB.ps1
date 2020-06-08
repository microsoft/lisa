# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
    Perform a simple VM hibernation in Azure
    This feature might be available in kernel 5.7 or later. By the time,
    customized kernel will be built.

.Description
    1. Prepare swap space for hibernation
    2. Compile a new kernel (optional)
    3. Update the grup.cfg with resume=UUID=xxxx where is from blkid swap disk
    4. Run the first fio testing
    5. Hibernate the VM, and verify the VM status
    5. Resume the VM and verify the VM status.
    6. Verify no kernel panic or call trace
    7. Run the second fio testing.
    8. Verify IOPS counts
    9. Run the thrid fio testing.
    10. In the middle of fio, hibernation starts.
    11. Verify no kernel panic or call trace after resume.
#>

param([object] $AllVmData, [string]$TestParams)

function Main {
    param($AllVMData, $TestParams)
    $currentTestResult = Create-TestResultObject
    try {
        $maxResumeWaitTime = 8
        $maxWakeupTime = 15
        $maxKernelCompileTime = 60
        $azurSyncTime = 30
        $testResult = $resultFail
        Write-LogDbg "Prepare swap space for VM $($AllVMData.RoleName) in RG $($AllVMData.ResourceGroupName)."
        # Prepare the swap space in the target VM
        $rgName = $AllVMData.ResourceGroupName
        $vmName = $AllVMData.RoleName
        $location = $AllVMData.Location
        $storageType = 'StandardSSD_LRS'
        $dataDiskName = $vmName + '_datadisk1'

        #region Generate constants.sh
        # We need to add extra parameters to constants.sh file apart from parameter properties defined in XML.
        # Hence, we are generating constants.sh file again in test script.

        Write-LogInfo "Generating constants.sh ..."
        $constantsFile = "$LogDir\constants.sh"
        foreach ($TestParam in $CurrentTestData.TestParameters.param) {
            Add-Content -Value "$TestParam" -Path $constantsFile
            Write-LogInfo "$TestParam added to constants.sh"
        }

        Write-LogInfo "constants.sh created successfully..."
        #endregion

        #region Add a new swap disk to Azure VM
        $diskConfig = New-AzDiskConfig -SkuName $storageType -Location $location -CreateOption Empty -DiskSizeGB 1024
        $dataDisk1 = New-AzDisk -DiskName $dataDiskName -Disk $diskConfig -ResourceGroupName $rgName

        $vm = Get-AzVM -Name $vmName -ResourceGroupName $rgName
        Start-Sleep -s $azurSyncTime
        $vm = Add-AzVMDataDisk -VM $vm -Name $dataDiskName -CreateOption Attach -ManagedDiskId $dataDisk1.Id -Lun 1
        Start-Sleep -s $azurSyncTime

        $ret_val = Update-AzVM -VM $vm -ResourceGroupName $rgName
        Write-LogInfo "Updated the VM with a new data disk"
        Write-LogInfo "Waiting for $azurSyncTime seconds for configuration sync"
        # Wait for disk sync with Azure host
        Start-Sleep -s $azurSyncTime

        # Verify the new data disk addition
        if ($ret_val.IsSuccessStatusCode) {
            Write-LogInfo "Successfully add a new disk to the Resource Group, $($rgName)"
        } else {
            Write-LogErr "Failed to add a new disk to the Resource Group, $($rgname)"
            throw "Failed to add a new disk"
        }

        #region Upload files to master VM
        foreach ($VMData in $AllVMData) {
            Copy-RemoteFiles -uploadTo $VMData.PublicIP -port $VMData.SSHPort -files "$constantsFile,$($CurrentTestData.files)" -username $user -password $password -upload
            Write-LogInfo "Copied the script files to the VM"
        }
        #endregion

        # Configuration for the hibernation
        Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "./SetupHbKernel.sh" -RunInBackground -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
        Write-LogInfo "Executed SetupHbKernel script inside VM"

        # Wait for kernel compilation completion. 60 min timeout
        $timeout = New-Timespan -Minutes $maxKernelCompileTime
        $sw = [diagnostics.stopwatch]::StartNew()
        while ($sw.elapsed -lt $timeout){
            $vmCount = $AllVMData.Count
            Wait-Time -seconds 15
            $state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "cat ~/state.txt"
            if ($state -eq "TestCompleted") {
                $kernelCompileCompleted = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "cat ~/constants.sh | grep setup_completed=0"
                if ($kernelCompileCompleted -ne "setup_completed=0") {
                    Write-LogErr "SetupHbKernel.sh run finished on $($VMData.RoleName) but setup was not successful!"
                } else {
                    Write-LogInfo "SetupHbKernel.sh finished on $($VMData.RoleName)"
                    $vmCount--
                }
                break
            } elseif ($state -eq "TestSkipped") {
                Write-LogInfo "SetupHbKernel.sh finished with SKIPPED state!"
                $resultArr = $resultSkipped
                $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
                return $currentTestResult.TestResult
            } elseif ($state -eq "TestFailed") {
                Write-LogErr "SetupHbKernel.sh didn't finish successfully!"
                $resultArr = $resultFail
                $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
                return $currentTestResult.TestResult
            } elseif ($state -eq "TestAborted") {
                Write-LogInfo "SetupHbKernel.sh finished with Aborted state!"
                $resultArr = $resultAborted
                $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
                return $currentTestResult.TestResult
            } else {
                Write-LogInfo "SetupHbKernel.sh is still running in the VM!"
            }
        }
        if ($vmCount -le 0){
            Write-LogInfo "SetupHbKernel.sh is done"
        } else {
            Throw "SetupHbKernel.sh didn't finish in the VM!"
        }

        # Reboot VM to apply swap setup changes
        Write-LogInfo "Rebooting All VMs!"
        $TestProvider.RestartAllDeployments($AllVMData)

        # Check the VM status before hibernation
        $vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
        if ($vmStatus.Statuses[1].DisplayStatus = "VM running") {
            Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is running before hibernation"
        } else {
            Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status before hibernation"
            throw "Can not identify VM status before hibernate"
        }

        # Run the first fio testing
        # After the first fio command, it sends out hibernate command.
        # and then the second fio test is running.
        $fioOverHibernateCommand = @"
date > timestamp.output
fio --size=10G --name=beforehb --direct=1 --ioengine=libaio --filename=fiodata --overwrite=1 --readwrite=readwrite --bs=1M --runtime=1 --iodepth=128 --numjobs=32 --runtime=300 --output-format=json+ --output=beforehb.json
sleep 1
rm -f fiodata
echo disk > /sys/power/state
sleep 1
fio --size=10G --name=afterhb --direct=1 --ioengine=libaio --filename=fiodata --overwrite=1 --readwrite=readwrite --bs=1M --runtime=1 --iodepth=128 --numjobs=32 --runtime=300 --output-format=json+ --output=afterhb.json
sleep 1
rm -f fiodata
date >> timestamp.output
"@
        Set-Content "$LogDir\fiotest.sh" $fioOverHibernateCommand
        # Upload test commands for fio and hibernation
        Copy-RemoteFiles -uploadTo $receiverVMData.PublicIP -port $receiverVMData.SSHPort -files "$LogDir\fiotest.sh" -username $user -password $password -upload -runAsSudo
        $testJob = Run-LinuxCmd -ip $receiverVMData.PublicIP -port $receiverVMData.SSHPort -username $user -password $password -command "bash ./fiotest.sh" -RunInBackground -runAsSudo
        Write-LogDbg "$testJob: Executed fio tests and following hibernation in the system. Waiting for $maxResumeWaitTime minutes until VM stopped"

        $timeout = New-Timespan -Minutes $maxResumeWaitTime
        $sw = [diagnostics.stopwatch]::StartNew()
        while ($sw.elapsed -lt $timeout){
            Write-LogInfo (Get-Date)
            Wait-Time -seconds $azurSyncTime
            if ($vmStatus.Statuses[1].DisplayStatus -eq "VM stopped") {
                break
            }
        }

        # Verify the VM status
        # Can not find if VM hibernation completion or not as soon as it disconnects the network. Assume it is in timeout.
        $vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
        if ($vmStatus.Statuses[1].DisplayStatus -eq "VM stopped") {
            Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is stopped after the first fio & hibernation command sent"
        } else {
            Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status after fio & hibernation command sent"
            throw "Can not identify VM status after hibernate"
        }

        # Resume the VM
        Start-AzVM -Name $vmName -ResourceGroupName $rgName -NoWait | Out-Null
        Write-LogInfo "Waked up the VM $vmName in Resource Group $rgName and continue checking its status in every 15 seconds until 15 minutes timeout "

        # Wait for VM resume for $maxWakeupTime min-timeout
        $timeout = New-Timespan -Minutes $maxWakeupTime
        $sw = [diagnostics.stopwatch]::StartNew()
        while ($sw.elapsed -lt $timeout){
            $vmCount = $AllVMData.Count
            Wait-Time -seconds 15
            $state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password "date"
            if ($state -eq 0) {
                Write-LogInfo "VM $($VMData.RoleName) resumed successfully"
                break
            } else {
                Write-LogInfo "VM is still resuming!"
            }
        }
        if ($vmCount -le 0){
            Write-LogInfo "VM resume completed"
        } else {
            throw "VM resume did not finish"
        }

        #Verify the VM status after power on event
        $vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
        if ($vmStatus.Statuses[1].DisplayStatus -eq "VM running") {
            Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is running after resuming"
        } else {
            Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Could not find the VM status after resuming"
            throw "Can not identify VM status after resuming"
        }

        # Verify kernel panic or call trace
        $calltrace_filter = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "dmesg | grep -i 'call trace'" -ignoreLinuxExitCode:$true

        if ($calltrace_filter -ne "") {
            Write-LogErr "Found Call Trace in dmesg"
            throw "Call trace in dmesg"
        } else {
            Write-LogInfo "Not found Call Trace in dmesg"
        }

        # Check the system log if it shows Power Management log
        "hibernation entry", "hibernation exit" | ForEach-Object {
            $pm_log_filter = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "dmesg | grep -i '$_'" -ignoreLinuxExitCode:$true
            Write-LogInfo "Searching the keyword: $_"
            if ($pm_log_filter -eq "") {
                Write-LogErr "Could not find Power Management log in dmesg"
                throw "Missing PM logging in dmesg"
            } else {
                Write-LogInfo "Successfully found Power Management log in dmesg"
                Write-LogInfo $pm_log_filter
            }
        }

        # verify fio test results.

        # Verify kernel panic or call trace
        $calltrace_filter = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "dmesg | grep -i 'call trace'" -ignoreLinuxExitCode:$true

        if ($calltrace_filter -ne "") {
            Write-LogErr "Found Call Trace in dmesg"
            throw "Call trace in dmesg"
        } else {
            Write-LogInfo "Not found Call Trace in dmesg"
        }

        $testResult = $resultPass
        Copy-RemoteFiles -downloadFrom $receiverVMData.PublicIP -port $receiverVMData.SSHPort -username $user -password $password -download -downloadTo $LogDir -files "*.json, *.log" -runAsSudo
    } catch {
        $ErrorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
        $resultArr = $testResult
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData