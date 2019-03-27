# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([object] $AllVmData, [object] $CurrentTestData)

$testScript = "golang-benchmark.sh"

function Start-TestExecution ($ip, $port) {
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

function Get-SQLQueryOfGolangBenchmark ($currentTestResult) {
    try {
        $guestSize = $allVMData.InstanceSize
        if ($TestPlatform -eq "HyperV") {
            $hyperVMappedSize = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
            $guestCPUNum = $hyperVMappedSize.HyperV.$HyperVInstanceSize.NumberOfCores
            $guestMemInMB = [int]($hyperVMappedSize.HyperV.$HyperVInstanceSize.MemoryInMB)
            $guestSize = "$($guestCPUNum)Cores $($guestMemInMB/1024)G"
        }
        $dataCsv = Import-Csv -Path $LogDir\golangBenchmark.csv
        $testItems = "binarytree,fasta,fannkuch,mandel,knucleotide,revcomp,nbody,spectralnorm,pidigits"
        $TestDate = $(Get-Date -Format yyyy-MM-dd)
        Write-LogInfo "Generating the performance data for database insertion"
        foreach ( $item in  $testItems.Split(",") ) {
            $resultMap = @{}
            $resultMap["GuestDistro"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type" | ForEach-Object {$_ -replace ",OS type,",""})
            $resultMap["HostOS"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version" | ForEach-Object {$_ -replace ",Host Version,",""})
            $resultMap["TestCaseName"] = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
            $resultMap["TestDate"] = $TestDate
            $resultMap["HostType"] = $TestPlatform
            $resultMap["HostBy"] = $TestLocation
            $resultMap["GuestOSType"] = 'Linux'
            $resultMap["GuestKernelVersion"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version" | ForEach-Object {$_ -replace ",Kernel version,",""})
            $resultMap["GuestSize"] = $guestSize
            $resultMap["GoVersion"] = $(Get-Content "$LogDir\VM_properties.csv" | Select-String "Go version" | ForEach-Object {$_ -replace ",Go Version,",""})
            $resultMap["Item"] = $item
            $resultMap["UserTimeInSeconds"] = [float] ( $dataCsv |  Where-Object { $_.Item -eq "$item"} | Select-Object UserTime ).UserTime
            $resultMap["WallClockTimeInSeconds"] = [float] ( $dataCsv |  Where-Object { $_.Item -eq "$item"} | Select-Object WallClockTime ).WallClockTime
            $resultMap["CPUUsage"] = [float] ( $dataCsv |  Where-Object { $_.Item -eq "$item"} | Select-Object CPUUsage ).CPUUsage.Replace("%","")
            $resultMap["MaximumResidentSetSizeInKbytes"] = [int] ( $dataCsv |  Where-Object { $_.Item -eq "$item"} | Select-Object MaximumResidentSetSize ).MaximumResidentSetSize
            $resultMap["VoluntaryContextSwitches"] = [int] ( $dataCsv  |  Where-Object { $_.Item -eq "$item"} | Select-Object VoluntaryContextSwitches ).VoluntaryContextSwitches
            $resultMap["InvoluntaryContextSwitches"] = [int] ( $dataCsv  |  Where-Object { $_.Item -eq "$item"} | Select-Object InvoluntaryContextSwitches ).InvoluntaryContextSwitches
            $resultMap["OperationsPerNs"] = [int64] ( $dataCsv  |  Where-Object { $_.Item -eq "$item"} | Select-Object Operations ).Operations
            $currentTestResult.TestResultData += $resultMap
        }
        Write-LogInfo ($dataCsv | Format-Table | Out-String)
    } catch {
        Write-LogErr "Getting the SQL query of test results failed"
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $errorMessage at line: $errorLine"
    }
}

function Main() {
    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    $testResult = $resultAborted
    try {
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
            Get-SQLQueryOfGolangBenchmark -currentTestResult  $currentTestResult
        }
    } catch {
        $errorMessage =  $_.Exception.Message
        $errorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $errorMessage at line: $errorLine"
    } Finally {
        if(!$testResult){
            $testResult = $resultAborted
        }
    }
    $resultArr += $testResult
    Write-LogInfo "Test result : $testResult"
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

# Main Body
Main
