# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

$testScript = "stress_web.sh"

function Start-TestExecution ($ip, $port)
{
    RunLinuxCmd -username $username -password $password -ip $ip -port $port -command "chmod +x *;touch /home/$username/state.txt" -runAsSudo
    LogMsg "Executing : ${testScript}"
    $cmd = "/home/$username/${testScript}"
    $testJob = RunLinuxCmd -username $username -password $password -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground
    while ((Get-Job -Id $testJob).State -eq "Running") {
        $currentStatus = RunLinuxCmd -username $username -password $password -ip $ip -port $port -command "cat /home/$username/state.txt"  -runAsSudo
        LogMsg "Current test status : $currentStatus"
        WaitFor -seconds 30
    }
    return $currentStatus
}

function Get-SQLQueryOfWebStress ($xmlConfig, $logDir)
{
    try {
        LogMsg "Getting the SQL query of test results..."
        $dataTableName = $xmlConfig.config.$TestPlatform.database.dbtable
        $TestCaseName = $currentTestData.testName
        $HostType = "$TestPlatform"
        $HostBy    = $TestLocation
        $HostOS = Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version" | ForEach-Object {$_ -replace ",Host Version,",""}
        $GuestOSType = "Linux"
        $GuestDistro = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type" | ForEach-Object {$_ -replace ",OS type,",""}
        $GuestSize = $allVMData[0].InstanceSize
        if ($TestPlatform -eq "HyperV") {
            $hyperVMappedSize = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
            $guestCPUNum = $hyperVMappedSize.HyperV.$HyperVInstanceSize.NumberOfCores
            $guestMemInMB = [int]($hyperVMappedSize.HyperV.$HyperVInstanceSize.MemoryInMB)
            $GuestSize = "$($guestCPUNum)Cores $($guestMemInMB/1024)G"
        }
        $GuestKernelVersion  = Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version" | ForEach-Object {$_ -replace ",Kernel version,",""}

        foreach ($param in $currentTestData.TestParameters.param) {
            if ($param -match "parallelConnections") {
                $parallelConnectionsList = $param.Replace("parallelConnections=","").Replace("'","")
            }
        }

        $dataCsv = Import-Csv -Path $LogDir\nginxStress.csv
        $testDate = Get-Date -Format yyyy-MM-dd
        $SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,GuestOSType,GuestDistro,GuestKernelVersion,GuestSize,NumThread,NumQuery,Accuracy,Query_per_sec,Msecs_per_connec,RuntimeSec) VALUES "
        foreach ($paralle in ($parallelConnectionsList -replace '\s{2,}', ' ').Trim().Split(" ") ) {
            $numQuery =  [int] ( $dataCsv |  Where-Object { $_.max_parallel -eq "$paralle"} | Select-Object fetches ).fetches
            $query_per_sec =  [float] ( $dataCsv |  Where-Object { $_.max_parallel -eq "$paralle"} | Select-Object fetches_per_sec ).fetches_per_sec
            $msecs_per_connec =  [float] ( $dataCsv |  Where-Object { $_.max_parallel -eq "$paralle"} | Select-Object msecs_per_connec ).msecs_per_connec
            $runtime =  [float] ( $dataCsv  |  Where-Object { $_.max_parallel -eq "$paralle"} | Select-Object seconds ).seconds
            $success_fetches =  [int] ( $dataCsv  |  Where-Object { $_.max_parallel -eq "$paralle"} | Select-Object success_fetches ).success_fetches
            $accuracy = [float] ($success_fetches / $numQuery)

            $SQLQuery += "('$TestCaseName','$testDate','$HostType','$HostBy','$HostOS','$GuestOSType','$GuestDistro','$GuestKernelVersion','$GuestSize','$paralle','$numQuery','$accuracy','$query_per_sec','$msecs_per_connec','$runtime'),"
        }
        $SQLQuery = $SQLQuery.TrimEnd(',')
        LogMsg "Getting the SQL query of test results:  done"
        return $SQLQuery
    } catch {
        LogErr "Getting the SQL query of test results:  ERROR"
        $errorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "EXCEPTION : $errorMessage at line: $ErrorLine"
    }
}

function Main()
{
    $currentTestResult = CreateTestResultObject
    $resultArr = @()
    $testResult = $resultAborted
    try
    {
        foreach ( $param in $currentTestData.TestParameters.param) {
            if ($param -imatch "testFileSizeInKb") {
                $fileSizeList = $param.Replace("testFileSizeInKb=","").Replace("'","")
            }
            if ($param -imatch "VF_IP1") {
                $clientSecondInternalIP = $param.Replace("VF_IP1=","")
            }
            if ($param -imatch "VF_IP2") {
                $serverSecondInternalIP = $param.Replace("VF_IP2=","")
            }
        }

        if ($TestPlatform -eq "Azure") {
            foreach ($vmData in $allVMData) {
                if ($vmData.RoleName -imatch "dependency") {
                    $serverPublicIP = $vmData.PublicIP
                    $serverSSHPort = $vmData.SSHPort
                    $serverSecondInternalIP = $($vmData.SecondInternalIP)
                } else {
                    $clientPublicIP = $vmData.PublicIP
                    $clientSSHPort = $vmData.SSHPort
                    $clientSecondInternalIP = $($vmData.SecondInternalIP)
                }
            }
        }

        if ($TestPlatform -eq "HyperV") {
            $clientSSHPort = $allVMData.SSHPort
            $clientPublicIP = $allVMData.PublicIP
            $serverSSHPort = $clientSSHPort
            $VM2Name = (Get-VM -ComputerName $DependencyVmHost | Where-Object {$_.Name -like "*-$RGIdentifier-*dependency*" }).Name
            $serverPublicIP = Get-IPv4ViaKVP $VM2Name $DependencyVmHost
        }

        LogMsg "CLIENT VM details :"
        LogMsg "  Public IP : $clientPublicIP "
        LogMsg "  Second Internal IP : $clientSecondInternalIP"
        LogMsg "  SSH Port : $clientSSHPort"

        LogMsg "SERVER VM details :"
        LogMsg "  Public IP : $serverPublicIP"
        LogMsg "  Second Internal IP : $serverSecondInternalIP"
        LogMsg "  SSH Port : $serverSSHPort"

        LogMsg "Install nginx on server vm: $serverPublicIP"
        $cmd = ". utils.sh && update_repos && install_package nginx"
        RunLinuxCmd -ip $serverPublicIP -port $serverSSHPort -username $username -password $password -command $cmd -runAsSudo

        foreach ($fileSize in ($fileSizeList -replace '\s{2,}', ' ').Trim().Split(" ") ) {
            $fileSize = [int]$fileSize
            $fileName = "file_${fileSize}K"
            LogMsg "Prepare file: /var/www/html/$fileName "
            $cmd = "dd if=/dev/zero of=/var/www/html/$fileName bs=1024 count=$fileSize"
            RunLinuxCmd -ip $serverPublicIP -port $serverSSHPort -username $username -password $password -command $cmd -runAsSudo
            $cmd = "echo http://${serverSecondInternalIP}/${fileName}  >> /home/${username}/urls"
            RunLinuxCmd -ip $clientPublicIP  -port $clientSSHPort -username $username -password $password -command $cmd -runAsSudo
        }

        Start-TestExecution -ip $clientPublicIP -port $clientSSHPort
        $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $testScript.split(".")[0] -TestType "sh" `
                      -PublicIP $clientPublicIP -SSHPort $clientSSHPort -Username $username -password $password `
                      -TestName $currentTestData.testName
        if ($testResult -imatch $resultPass) {
            Remove-Item "$LogDir\*.csv" -Force
            $remoteFiles = "nginxStress.csv,VM_properties.csv,TestExecution.log,web_test_results.tar.gz"
            RemoteCopy -download -downloadFrom $clientPublicIP -files $remoteFiles -downloadTo $LogDir -port $clientSSHPort -username $username -password $password
            $checkValues = "$resultPass,$resultFail,$resultAborted"
            $CurrentTestResult.TestSummary += CreateResultSummary -testResult $testResult -metaData "" -checkValues $checkValues -testName $currentTestData.testName
            $webStressSQLQuery = Get-SQLQueryOfWebStress -xmlConfig $xmlConfig -logDir $LogDir
            if ($webStressSQLQuery) {
                UploadTestResultToDatabase -SQLQuery $webStressSQLQuery
            }
        }
    } catch {
        $testResult = $resultAborted
        $errorMessage =  $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        LogErr "EXCEPTION : $errorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = $resultAborted
        }
    }

    $resultArr += $testResult
    LogMsg "Test result : $testResult"
    $currentTestResult.TestResult = GetFinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

# Main Body
Main
