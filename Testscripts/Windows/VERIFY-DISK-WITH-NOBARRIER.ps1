# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
function Main {

    try {
        $count = 0
        $VM = $allVMData
        $ResourceGroupUnderTest = $VM.ResourceGroupName
        $VirtualMachine = Get-AzureRmVM -ResourceGroupName $VM.ResourceGroupName -Name $VM.RoleName
        $diskCount = (Get-AzureRmVMSize -Location $allVMData.Location | Where-Object {$_.Name -eq $allVMData.InstanceSize}).MaxDataDiskCount
        Write-LogInfo "Max $diskCount Disks are attach to VM"
        Write-LogInfo "--------------------------------------------------------"
        Write-LogInfo "Serial Addition of Data Disks"
        Write-LogInfo "--------------------------------------------------------"
        While ($count -lt $diskCount) {
            $count += 1
            $verifiedDiskCount = 0
            $diskName = "disk" + $count.ToString()
            $diskSizeinGB = "10"
            $VHDuri = $VirtualMachine.StorageProfile.OsDisk.Vhd.Uri
            $VHDUri = $VHDUri.Replace("osdisk", $diskName)
            Write-LogInfo "Adding an empty data disk of size $diskSizeinGB GB, $count"
            $Null = Add-AzureRMVMDataDisk -VM $VirtualMachine -Name $diskName -DiskSizeInGB $diskSizeinGB -LUN $count -VhdUri $VHDuri.ToString() -CreateOption Empty
            Write-LogInfo "Successfully created an empty data disk of size $diskSizeinGB GB,$count"
            $Null = Update-AzureRMVM -VM $VirtualMachine -ResourceGroupName $ResourceGroupUnderTest
            Write-LogInfo "Successfully added an empty data disk to the VM of size $diskSizeinGB, $count"
            Write-LogInfo "Verifying if data disk is added to the VM: Running fdisk on remote VM"
            $fdiskOutput = Run-LinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
            foreach ($line in ($fdiskOutput.Split([Environment]::NewLine))) {
                if ($line -imatch "Disk /dev/sd[^ab]" -and ([int]($line.Split()[2]) -ge [int]$diskSizeinGB)) {
                    Write-LogInfo "Data disk is successfully mounted to the VM: $line"
                    $verifiedDiskCount += 1
                }
            }
        }
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort -files $currentTestData.files -username $user -password $password -upload
        $null = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "chmod +x *" -runAsSudo
        $testJob = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $user -password $password -command "bash /home/$user/nobarrier.sh > nobarrierConsole.txt" -RunInBackground -runAsSudo
        while ( (Get-Job -Id $testJob).State -eq "Running" ) {
            $currentStatus = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "tail -1 /home/$user/nobarrierConsole.txt" -runAsSudo
            Write-LogInfo "Current Test Status : $currentStatus"
            Wait-Time -seconds 20
        }
        $finalStatus = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "cat /home/$user/state.txt" -runAsSudo
        if ( $finalStatus -imatch "TestFailed") {
            Write-LogErr "Test failed. Last known status : $currentStatus."
            $testResult = "FAIL"
        }
        elseif ( $finalStatus -imatch "TestAborted") {
            Write-LogErr "Test Aborted. Last known status : $currentStatus."
            $testResult = "ABORTED"
        }
        elseif ( $finalStatus -imatch "TestCompleted") {
            Write-LogInfo "Test Completed."
            $testResult = "PASS"
        }
        $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$($allVMData.InstanceSize) : Number of Disk Attached - $diskCount" `
            -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "Aborted"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$($allVMData.InstanceSize) : Number of Disk Attached - $diskCount" `
                -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

Main
