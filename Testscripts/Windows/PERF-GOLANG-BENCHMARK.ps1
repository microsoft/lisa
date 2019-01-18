# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([object] $AllVmData, [object] $CurrentTestData)

$testScript = "golang-benchmark.sh"

function Start-TestExecution ($ip, $port)
{
    Run-LinuxCmd -username $username -password $password -ip $ip -port $port -command "chmod a+x *.sh" -runAsSudo
    Write-LogInfo "Executing : ${testScript}"
    $cmd = "bash /home/$username/${testScript}"
    $testJob = Run-LinuxCmd -username $username -password $password -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground
    while ((Get-Job -Id $testJob).State -eq "Running") {
        $currentStatus = Run-LinuxCmd -username $username -password $password -ip $ip -port $port -command "cat /home/$username/state.txt"  -runAsSudo
        Write-LogInfo "Current test status : $currentStatus"
        Wait-Time -seconds 30
    }
}

function Get-SQLQueryOfGolangBenchmark ( )
{
    try {
        Write-LogInfo "Getting the SQL query of test results..."
        $dataTableName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbtable
        $testCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
        $hostOS = Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version" | ForEach-Object {$_ -replace ",Host Version,",""}
        $goVersion = Get-Content "$LogDir\VM_properties.csv" | Select-String "Go version" | ForEach-Object {$_ -replace ",Go Version,",""}
        $guestDistro = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type" | ForEach-Object {$_ -replace ",OS type,",""}
        $guestSize = $allVMData.InstanceSize
        if ($TestPlatform -eq "HyperV") {
            $hyperVMappedSize = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
            $guestCPUNum = $hyperVMappedSize.HyperV.$HyperVInstanceSize.NumberOfCores
            $guestMemInMB = [int]($hyperVMappedSize.HyperV.$HyperVInstanceSize.MemoryInMB)
            $guestSize = "$($guestCPUNum)Cores $($guestMemInMB/1024)G"
        }
        $GuestKernelVersion  = Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version" | ForEach-Object {$_ -replace ",Kernel version,",""}
        $dataCsv = Import-Csv -Path $LogDir\golangBenchmark.csv
        $testDate = Get-Date -Format yyyy-MM-dd
        $SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,GuestOSType,GuestDistro,GuestKernelVersion,GuestSize,GoVersion,Item,UserTimeInSeconds,WallClockTimeInSeconds,CPUUsage,MaximumResidentSetSizeInKbytes,VoluntaryContextSwitches,InvoluntaryContextSwitches,OperationsPerNs) VALUES "
        $testItems = "binarytree,fasta,fannkuch,mandel,knucleotide,revcomp,nbody,spectralnorm,pidigits"
        foreach ( $item in  $testItems.Split(",") ) {
            $userTime = [float] ( $dataCsv |  Where-Object { $_.Item -eq "$item"} | Select-Object UserTime ).UserTime
            $wallClockTime = [float] ( $dataCsv |  Where-Object { $_.Item -eq "$item"} | Select-Object WallClockTime ).WallClockTime
            $CPUUsage = [float] ( $dataCsv |  Where-Object { $_.Item -eq "$item"} | Select-Object CPUUsage ).CPUUsage.Replace("%","")
            $maximumResidentSetSize =  [int] ( $dataCsv |  Where-Object { $_.Item -eq "$item"} | Select-Object MaximumResidentSetSize ).MaximumResidentSetSize
            $voluntaryContextSwitches =  [int] ( $dataCsv  |  Where-Object { $_.Item -eq "$item"} | Select-Object VoluntaryContextSwitches ).VoluntaryContextSwitches
            $involuntaryContextSwitches =  [int] ( $dataCsv  |  Where-Object { $_.Item -eq "$item"} | Select-Object InvoluntaryContextSwitches ).InvoluntaryContextSwitches
            $operations =  [int64] ( $dataCsv  |  Where-Object { $_.Item -eq "$item"} | Select-Object Operations ).Operations
            $SQLQuery += "('$testCaseName','$testDate','$TestPlatform','$TestLocation','$hostOS','Linux','$guestDistro','$GuestKernelVersion','$guestSize','$goVersion','$item','$userTime','$wallClockTime','$CPUUsage','$maximumResidentSetSize','$voluntaryContextSwitches','$involuntaryContextSwitches','$operations'),"
        }
        $SQLQuery = $SQLQuery.TrimEnd(',')
        Write-LogInfo "Getting the SQL query of test results: done"
        return $SQLQuery
    } catch {
        Write-LogErr "Getting the SQL query of test results failed"
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $errorMessage at line: $errorLine"
    }
}

function Main()
{
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    $testResult = $resultAborted
    try
    {
        $hs1VIP = $AllVMData.PublicIP
        $port = $AllVMData.SSHPort
        Start-TestExecution -ip $hs1VIP -port $port
        $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $testScript.split(".")[0] -TestType "sh" `
                      -PublicIP $hs1VIP -SSHPort $port -Username $username -password $password `
                      -TestName $currentTestData.testName
        if ($testResult -imatch $resultPass) {
            Remove-Item "$LogDir\*.csv" -Force
            $remoteFiles = "golangBenchmark.csv,VM_properties.csv,TestExecution.log,test_results.tar.gz"
            Copy-RemoteFiles -download -downloadFrom $hs1VIP -files $remoteFiles -downloadTo $LogDir -port $port -username $username -password $password
            $checkValues = "$resultPass,$resultFail,$resultAborted"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "" -checkValues $checkValues -testName $currentTestData.testName
            $golangSQLQuery = Get-SQLQueryOfGolangBenchmark
            if ($golangSQLQuery) {
                Upload-TestResultToDatabase -SQLQuery $golangSQLQuery
            }
        }
    }
    catch
    {
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $errorMessage at line: $errorLine"
    }
    Finally
    {
        if(!$testResult){
            $testResult = $resultAborted
        }
    }
    $resultArr += $testResult
    Write-LogInfo "Test result : $testResult"
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult.TestResult
}

# Main Body
Main
