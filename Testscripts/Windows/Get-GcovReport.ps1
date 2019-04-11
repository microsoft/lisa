# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([String] $TestParams, [object] $AllVmData)

$gcovScript = "generate_gcov.sh"
$reportScript = "generate_gcov_report.sh"

$WORK_DIR = "/reporting"

function Main() {
    $publicIP = $AllVMData.PublicIP
    $port = $AllVMData.SSHPort
    $currentTestResult = Create-TestResultObject

    $params = @{}
    $TestParams.Split(";") | ForEach-Object {
        $arg = $_.Split("=")[0]
        $val = $_.Split("=")[1]
		# Debug
		Write-LogInfo "ARG: $arg , VAL: $val"

        $params[$arg] = $val
    }

	$remoteBuildDir = $params["BUILD_DIR"]
	$logsPath = $params["LOCAL_LOGS_PATH"]
	$testCategory = $params["TEST_CATEGORY"]

	$sourcesPath = $params["LOCAL_SRC_PATH"]
	$sourcesPath = Resolve-Path $sourcesPath
	if ( -not (Test-Path $sourcesPath)) {
		Write-LogErr "Cannot find sources archive"
		throw "sources doesn't exist"
	}
	$sourcesName = Split-Path $sourcesPath -Leaf
	Copy-RemoteFiles -uploadTo $publicIP -port $port -username $username -password $password -upload `
        -files "$sourcesPath"
	$null = Run-LinuxCmd -username $user -password $password `
        -ip $publicIP -port $port -runAsSudo `
		-command "tar xzf ${sourcesName} -C /"

	Get-ChildItem -Recurse -Path $logsPath -Include "gcov*.gz" | ForEach-Object {
		$fullPath = $_.FullName
		$logName = $_.Name
		$testName = $_.Directory.Name

		Copy-RemoteFiles -uploadTo $publicIP -port $port -username $username -password $password -upload `
			-files "$fullPath"
		$null = Run-LinuxCmd -username $user -password $password `
			-ip $publicIP -port $port -runAsSudo `
			-command "bash /home/$username/${gcovScript} --test_category ${testCategory} --test_name ${testName} --work_dir ${WORK_DIR} --build_dir ${remoteBuildDir} --archive_name ${logName}"
	}

    $null = Run-LinuxCmd -username $user -password $password `
        -ip $publicIP -port $port -runAsSudo `
        -command "bash /home/$username/${reportScript} --build_dir ${remoteBuildDir} --test_category ${testCategory} --gcov_path ${WORK_DIR}/gcov"

    Copy-RemoteFiles -download -downloadFrom $publicIP -files "${testCategory}.zip" `
        -downloadTo ".\CodeCoverage\" -port $port -username $username -password $password

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr "PASS"
    return $currentTestResult
}

Main