# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
Import-Module .\TestLibs\RDFELibs.psm1 -Force
$result = ""
$testResult = ""
$resultArr = @()

try
{
    $isDeployed = Deploy-VMs -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
    if ($isDeployed)
    {
        foreach ($VM in $allVMData)
        {
            $ResourceGroupUnderTest = $VM.ResourceGroupName
            $VirtualMachine = Get-AzureRmVM -ResourceGroupName $VM.ResourceGroupName -Name $VM.RoleName
            $diskCount = (Get-AzureRmVMSize -Location $allVMData.Location | Where-Object {$_.Name -eq $allVMData.InstanceSize}).MaxDataDiskCount
            Write-LogInfo "--------------------------------------------------------"
            Write-LogInfo "Serial Addition and Removal of Data Disks"
            Write-LogInfo "--------------------------------------------------------"
            While($count -lt $diskCount)
            {
                $count += 1
                $verifiedDiskCount = 0
                $diskName = "disk"+ $count.ToString()
                $diskSizeinGB = "1023"
                $VHDuri = $VirtualMachine.StorageProfile.OsDisk.Vhd.Uri
                $VHDUri = $VHDUri.Replace("osdisk",$diskName)
                Write-LogInfo "Adding an empty data disk of size $diskSizeinGB GB"
                $null = Add-AzureRMVMDataDisk -VM $VirtualMachine -Name $diskName -DiskSizeInGB $diskSizeinGB -LUN $count -VhdUri $VHDuri.ToString() -CreateOption Empty
                Write-LogInfo "Successfully created an empty data disk of size $diskSizeinGB GB"

                #Write-LogInfo "Number of data disks added to the VM $count"
                $null = Update-AzureRMVM -VM $VirtualMachine -ResourceGroupName $ResourceGroupUnderTest
                Write-LogInfo "Successfully added an empty data disk to the VM of size $diskSizeinGB"
                Write-LogInfo "Verifying if data disk is added to the VM: Running fdisk on remote VM"
                $fdiskOutput = Run-LinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo

                foreach($line in ($fdiskOutput.Split([Environment]::NewLine)))
                {
                    if($line -imatch "Disk /dev/sd[^ab]" -and ([int]($line.Split()[2]) -ge [int]$diskSizeinGB))
                    {
                        Write-LogInfo "Data disk is successfully mounted to the VM: $line"
                        $verifiedDiskCount += 1
                    }
                }

                #Write-LogInfo "Number of data disks verified inside VM $verifiedDiskCount"
                if($verifiedDiskCount -eq 1)
                {
                    Write-LogInfo "Data disk added to the VM is successfully verified inside VM"
                    #$testResult = "PASS"
                }
                else
                {
                    Write-LogInfo "Data disk added to the VM failed to verify inside VM"
                    $testResult = "FAIL"
                    Break
                }
                #Write-LogInfo "------------------------------------------"
                Write-LogInfo "Removing the Data Disks from the VM"
                $null = Remove-AzureRmVMDataDisk -VM $VirtualMachine -DataDiskNames $diskName
                $null = Update-AzureRMVM -VM $VirtualMachine -ResourceGroupName $ResourceGroupUnderTest
                Write-LogInfo "Successfully removed the data disk from the VM"
                Write-LogInfo "Verifying if data disk is removed from the VM: Running fdisk on remote VM"

                $fdiskFinalOutput = Run-LinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
                foreach($line in ($fdiskFinalOutput.Split([Environment]::NewLine)))
                {
                    if($line -imatch "Disk /dev/sd[^ab]" -and ([int]($line.Split()[2]) -ge [int]$diskSizeinGB))
                    {
                        Write-LogInfo "Data disk is NOT removed from the VM at $line"
                        $testResult = "FAIL"
                        Break
                    }
                }
                Write-LogInfo "Successfully verified that data disk is removed from the VM"
                Write-LogInfo "--------------------------------------------------------"
                #$testResult = "PASS"
            }
            Write-LogInfo "Successfully added and removed $diskCount number of data disks"
            $testResult = "PASS"
        }
    }
}
catch
{
    $ErrorMessage =  $_.Exception.Message
    Write-LogInfo "EXCEPTION : $ErrorMessage"
}
Finally
    {
        if (!$testResult)
        {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }
$result = Get-FinalResultHeader -resultarr $resultArr

#Clean up the setup
Do-TestCleanUp -result $result -testName $currentTestData.testName -ResourceGroups $isDeployed

#Return the result and summery to the test suite script..
return $result
