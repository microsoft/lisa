# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([String] $TestParams, [object] $AllVmData)

$testScript = "build_gcov_kernel.sh"

function Main() {
    $publicIP = $AllVMData.PublicIP
    $port = $AllVMData.SSHPort
    $currentTestResult = Create-TestResultObject
    $testResult = "Aborted"

    $params = @{}
    $TestParams.Split(";") | ForEach-Object {
        $arg = $_.Split("=")[0]
        $val = $_.Split("=")[1]
        $params[$arg] = $val
    }

    $sourceDest = $params["SOURCE_DEST"]
    $packageDest = $params["PACKAGE_DEST"]
    if (( -not $sourceDest) -and ( -not $packageDest)) {
        Write-LogErr "Cannot find destination parameters"
        $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $testResult
        return $currentTestResult
    }
    $srcLocalUrl = $params["SRC_PACKAGE_PATH"]
    $srcLocalUrl = Resolve-Path $srcLocalUrl
    Write-LogInfo "PATH: $srcLocalUrl"

    $srcLocalUrl = Resolve-Path $srcLocalUrl
    if ( -not (Test-Path $srcLocalUrl)) {
        Write-LogErr "Cannot find local source package in path: $srcLocalUrl"
        $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $testResult
        return $currentTestResult
    }

    Copy-RemoteFiles -uploadTo $publicIP -port $port -username $username -password $password -upload `
        -files "$srcLocalUrl"

    $null = Run-LinuxCmd -username $user -password $password `
        -ip $publicIP -port $port -command "chmod a+x *.sh" -runAsSudo
    $null = Run-LinuxCmd -username $username -runMaxAllowedTime 6000 `
        -password $password -ip $publicIP -port $port `
        -command "bash /home/$username/${testScript} > debug.log 2>&1" -runAsSudo

    $buildResult = Run-LinuxCmd -username $user -password $password `
        -ip $publicIP -port $port -command "cat ./results.txt" -runAsSudo
    Write-LogInfo "Build result: $buildResult"
    if ($buildResult -NotMatch "BUILD_SUCCEDED") {
        $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $testResult
        return $currentTestResult
    }

    if (Test-Path ".\CodeCoverage") {
        Remove-Item -Path ".\CodeCoverage" -Recurse -Force
    }
    New-Item -Type directory -Path ".\CodeCoverage\artifacts"

    Copy-RemoteFiles -download -downloadFrom $publicIP -files "${sourceDest},${packageDest}" `
        -downloadTo ".\CodeCoverage\artifacts" -port $port -username $username -password $password

    $testResult = "PASS"
    Write-LogInfo "Code coverage artifacts successfully downloaded in dir: CodeCoverage\artifacts"

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $testResult
    return $currentTestResult
}

Main
