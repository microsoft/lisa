# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
Import-Module .\TestLibs\RDFELibs.psm1 -Force
$result = ""
$testResult = ""
$resultArr = @()

try
{
    $isDeployed = DeployVMS -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
    if ($isDeployed)
    {
        foreach ($VM in $allVMData)
        {
            $ResourceGroupUnderTest = $VM.ResourceGroupName
            $VirtualMachine = Get-AzureRmVM -ResourceGroupName $VM.ResourceGroupName -Name $VM.RoleName
            $diskCount = (Get-AzureRmVMSize -Location $allVMData.Location | Where-Object {$_.Name -eq $allVMData.InstanceSize}).MaxDataDiskCount
            LogMsg "--------------------------------------------------------"
            LogMsg "Serial Addition and Removal of Data Disks"
            LogMsg "--------------------------------------------------------"
            While($count -lt $diskCount)
            {
                $count += 1
                $verifiedDiskCount = 0
                $diskName = "disk"+ $count.ToString()
                $diskSizeinGB = "1023"
                $VHDuri = $VirtualMachine.StorageProfile.OsDisk.Vhd.Uri
                $VHDUri = $VHDUri.Replace("osdisk",$diskName)
                LogMsg "Adding an empty data disk of size $diskSizeinGB GB"
                $out = Add-AzureRMVMDataDisk -VM $VirtualMachine -Name $diskName -DiskSizeInGB $diskSizeinGB -LUN $count -VhdUri $VHDuri.ToString() -CreateOption Empty
                LogMsg "Successfully created an empty data disk of size $diskSizeinGB GB"                

                #LogMsg "Number of data disks added to the VM $count"
                $out = Update-AzureRMVM -VM $VirtualMachine -ResourceGroupName $ResourceGroupUnderTest
                LogMsg "Successfully added an empty data disk to the VM of size $diskSizeinGB"
                LogMsg "Verifying if data disk is added to the VM: Running fdisk on remote VM"
                $fdiskOutput = RunLinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo

                foreach($line in ($fdiskOutput.Split([Environment]::NewLine)))
                {
                    if($line -imatch "Disk /dev/sd[^ab]" -and ([int]($line.Split()[2]) -ge [int]$diskSizeinGB))
                    {
                        LogMsg "Data disk is successfully mounted to the VM: $line"
                        $verifiedDiskCount += 1
                    }
                }

                #LogMsg "Number of data disks verified inside VM $verifiedDiskCount"
                if($verifiedDiskCount -eq 1)
                {
                    LogMsg "Data disk added to the VM is successfully verified inside VM"
                    #$testResult = "PASS"
                }
                else
                {
                    LogMsg "Data disk added to the VM failed to verify inside VM"
                    $testResult = "FAIL"
                    Break
                }
                #LogMsg "------------------------------------------"
                LogMsg "Removing the Data Disks from the VM"
                $out = Remove-AzureRmVMDataDisk -VM $VirtualMachine -DataDiskNames $diskName
                $out = Update-AzureRMVM -VM $VirtualMachine -ResourceGroupName $ResourceGroupUnderTest
                LogMsg "Successfully removed the data disk from the VM"
                LogMsg "Verifying if data disk is removed from the VM: Running fdisk on remote VM"

                $fdiskFinalOutput = RunLinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
                foreach($line in ($fdiskFinalOutput.Split([Environment]::NewLine)))
                {
                    if($line -imatch "Disk /dev/sd[^ab]" -and ([int]($line.Split()[2]) -ge [int]$diskSizeinGB))
                    {
                        LogMsg "Data disk is NOT removed from the VM at $line"
                        $testResult = "FAIL"
                        Break
                    }
                }
                LogMsg "Successfully verified that data disk is removed from the VM"
                LogMsg "--------------------------------------------------------"
                #$testResult = "PASS"
            }
            LogMsg "Successfully added and removed $diskCount number of data disks"
            $testResult = "PASS"
        }
    }
}
catch
{
    $ErrorMessage =  $_.Exception.Message
    LogMsg "EXCEPTION : $ErrorMessage" 
}
Finally
    {
        if (!$testResult)
        {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }   
$result = GetFinalResultHeader -resultarr $resultArr

#Clean up the setup
DoTestCleanUp -result $result -testName $currentTestData.testName -ResourceGroups $isDeployed

#Return the result and summery to the test suite script..
return $result
