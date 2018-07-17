# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
$result = ""
$CurrentTestResult = CreateTestResultObject
$resultArr = @()
$vmSizes = @()

try
{
    $isDeployed = DeployVMS -setupType $currentTestData.setupType -Distro $Distro -xmlConfig $xmlConfig
    if($isDeployed)
    {
        foreach ($VM in $allVMData)
        {
            $VirtualMachine = Get-AzureRmVM -ResourceGroupName $VM.ResourceGroupName -Name $VM.RoleName
            $vmSizes = (Get-AzureRmVMSize -ResourceGroupName $VM.ResourceGroupName -VMName $VM.RoleName).Name
            LogMsg "Deployed VM will be resized to the following VM sizes: $vmSizes"
            foreach ($vmSize in $vmSizes)
            {
                LogMsg "--------------------------------------------------------"
                LogMsg "Resizing the VM to size: $vmSize"
                $VirtualMachine.HardwareProfile.VmSize = $vmSize
                Update-AzureRmVM -VM $VirtualMachine -ResourceGroupName $VM.ResourceGroupName
                LogMsg "Resize the VM to size: $vmSize is successful"
                
                #Add CPU count and RAM checks
                $expectedVMSize = Get-AzureRmVMSize -Location $allVMData.Location | Where-Object {$_.Name -eq $vmSize}
                $expectedCPUCount = $expectedVMSize.NumberOfCores
                $expectedRAMSizeinMB = $expectedVMSize.MemoryInMB
                   
                $actualCPUCount = RunLinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "nproc"
                $actualRAMSizeinKB = RunLinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "cat /proc/meminfo | grep -i memtotal | awk '{ print `$`2 }'"
                $actualRAMSizeinMB = $actualRAMSizeinKB/1024

                LogMsg "Expected CPU Count: $expectedCPUCount"
                LogMsg "Actual CPU Count in VM: $actualCPUCount"
                LogMsg "Expected RAM Size in MB: $expectedRAMSizeinMB"
                LogMsg "Actual RAM Size in MB in VM: $actualRAMSizeinMB"
                                
                if ($expectedCPUCount -eq $actualCPUCount)
                { 
                    LogMsg "CPU Count verification is SUCCESS"
                    if($actualRAMSizeinMB -ne $expectedRAMSizeinMB)
                    {
                        LogWarn "RAM Size within VM is NOT equal to the expected RAM size"
                    }
                }
                else {
                    LogErr "CPU count verification failed"
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
$CurrentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr

#Clean up the setup
DoTestCleanUp -CurrentTestResult $CurrentTestResult -testName $currentTestData.testName -ResourceGroups $isDeployed

#Return the result and summary to the test suite script..
return $CurrentTestResult
