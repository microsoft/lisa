# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
$CurrentTestResult = Create-TestResultObject
$resultArr = @()
$vmSizes = @()

try
{
    $isDeployed = Deploy-VMs -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
    if($isDeployed)
    {
        foreach ($VM in $allVMData)
        {
            $VirtualMachine = Get-AzureRmVM -ResourceGroupName $VM.ResourceGroupName -Name $VM.RoleName
            $vmSizes = (Get-AzureRmVMSize -ResourceGroupName $VM.ResourceGroupName -VMName $VM.RoleName).Name
            Write-LogInfo "Deployed VM will be resized to the following VM sizes: $vmSizes"
            foreach ($vmSize in $vmSizes)
            {
                Write-LogInfo "--------------------------------------------------------"
                Write-LogInfo "Resizing the VM to size: $vmSize"
                $VirtualMachine.HardwareProfile.VmSize = $vmSize
                Update-AzureRmVM -VM $VirtualMachine -ResourceGroupName $VM.ResourceGroupName
                Write-LogInfo "Resize the VM to size: $vmSize is successful"

                #Add CPU count and RAM checks
                $expectedVMSize = Get-AzureRmVMSize -Location $allVMData.Location | Where-Object {$_.Name -eq $vmSize}
                $expectedCPUCount = $expectedVMSize.NumberOfCores
                $expectedRAMSizeinMB = $expectedVMSize.MemoryInMB

                $actualCPUCount = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "nproc"
                $actualRAMSizeinKB = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "cat /proc/meminfo | grep -i memtotal | awk '{ print `$`2 }'"
                $actualRAMSizeinMB = $actualRAMSizeinKB/1024

                Write-LogInfo "Expected CPU Count: $expectedCPUCount"
                Write-LogInfo "Actual CPU Count in VM: $actualCPUCount"
                Write-LogInfo "Expected RAM Size in MB: $expectedRAMSizeinMB"
                Write-LogInfo "Actual RAM Size in MB in VM: $actualRAMSizeinMB"

                if ($expectedCPUCount -eq $actualCPUCount)
                {
                    Write-LogInfo "CPU Count verification is SUCCESS"
                    if($actualRAMSizeinMB -ne $expectedRAMSizeinMB)
                    {
                        Write-LogWarn "RAM Size within VM is NOT equal to the expected RAM size"
                    }
                }
                else {
                    Write-LogErr "CPU count verification failed"
                    $testResult = "FAIL"
                }

            }
        }
        $testResult = "PASS"

    }
}
catch
{
    $ErrorMessage =  $_.Exception.Message
    $ErrorLine = $_.InvocationInfo.ScriptLineNumber
    Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
}
Finally
    {
        if (!$testResult)
        {
            $testResult = "Aborted"
        }
        $resultArr += $testResult
    }
$CurrentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr

#Clean up the setup
Do-TestCleanUp -CurrentTestResult $CurrentTestResult -testName $currentTestData.testName -ResourceGroups $isDeployed

#Return the result and summary to the test suite script..
return $CurrentTestResult
