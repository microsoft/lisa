##############################################################################################
# TestLogs.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module handles log files.

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################
Function Write-Log() {
	param
	(
		[ValidateSet('INFO', 'WARN', 'ERROR', 'DEBUG', IgnoreCase = $false)]
		[string]$logLevel,
		[string]$text
	)

	if ($password) {
		$text = $text.Replace($password, "******")
	}
	$now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
	$logType = $logLevel.PadRight(5, ' ')
	$finalMessage = "$now : [$logType] $text"
	$fgColor = "White"
	switch ($logLevel) {
		"INFO"	{ $fgColor = "White"; continue }
		"WARN"	{ $fgColor = "Yellow"; continue }
		"ERROR"	{ $fgColor = "Red"; continue }
		"DEBUG"	{ $fgColor = "DarkGray"; continue }
	}
	Write-Host $finalMessage -ForegroundColor $fgColor

	try {
		if ($LogDir) {
			if (!(Test-Path $LogDir)) {
				New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
			}
		}
		else {
			$LogDir = $env:TEMP
		}
		if (!$LogFileName) {
			$LogFileName = "LISAv2-Test-$(Get-Date -Format 'yyyy-MM-dd-HH-mm-ss-ffff').log"
		}
		$LogFileFullPath = Join-Path $LogDir $LogFileName
		if (!(Test-Path $LogFileFullPath)) {
			New-Item -path $LogDir -name $LogFileName -type "file" | Out-Null
		}
		Add-Content -Value $finalMessage -Path $LogFileFullPath -Force
	}
	catch {
		Write-Output "[LOG FILE EXCEPTION] : $now : $text"
	}
}

Function Write-LogInfo($text) {
	Write-Log "INFO" $text
}

Function Write-LogErr($text) {
	Write-Log "ERROR" $text
}

Function Write-LogWarn($text) {
	Write-Log "WARN" $text
}

Function Write-LogDbg($text) {
	Write-Log "DEBUG" $text
}

function Collect-TestLogs {
	<#
	.DESCRIPTION
	Collects logs created by the test script.
	The function collects logs only if a shell/python test script is executed.
	#>

	param(
		[string]$LogsDestination,
		[string]$ScriptName,
		[string]$PublicIP,
		[string]$SSHPort,
		[string]$Username,
		[string]$Password,
		[string]$TestType,
		[string]$TestName
	)
	# Note: This is a temporary solution until a standard is decided
	# for what string py/sh scripts return
	$resultTranslation = @{"TestCompleted" = $global:ResultPass;
		"TestSkipped"                         = $global:ResultSkipped;
		"TestFailed"                          = $global:ResultFail;
		"TestAborted"                         = $global:ResultAborted;
	}

	$currentTestResult = Create-TestResultObject

	if ($TestType -eq "sh") {
		$filesTocopy = "./state.txt, ./*summary.log, ./TestExecution.log, ./TestExecutionError.log"
		Copy-RemoteFiles -download -downloadFrom $PublicIP -downloadTo $LogsDestination `
			-Port $SSHPort -Username $Username -password $Password `
			-files $filesTocopy
		$summary = Get-Content (Join-Path $LogDir "summary.log")
		$testState = Get-Content (Join-Path $LogDir "state.txt")
		# If test has timed out state.txt will contain TestRunning
		if ($testState -eq "TestRunning") {
			$currentTestResult.TestResult = $global:ResultAborted
		}
		else {
			$currentTestResult.TestResult = $resultTranslation[$testState]
		}
		if (!$currentTestResult.TestSummary -and $summary) {
			$summary | ForEach-Object {
				$currentTestResult.TestSummary += New-ResultSummary -testResult ($_ -replace '{(.*)}', '[$1]')
			}
		}
	}
	elseif ($TestType -eq "py") {
		$filesTocopy = "./state.txt, ./Summary.log, ./${TestName}_summary.log"
		Copy-RemoteFiles -download -downloadFrom $PublicIP -downloadTo $LogsDestination `
			-Port $SSHPort -Username $Username -password $Password `
			-files $filesTocopy
		$summary = Get-Content (Join-Path $LogDir "Summary.log")
		$currentTestResult.TestResult = $summary
	}

	Write-LogInfo "TEST SCRIPT SUMMARY ~~~~~~~~~~~~~~~"
	$summary | ForEach-Object {
		Write-Host $_ -ForegroundColor Gray -BackgroundColor White
	}
	Write-LogInfo "END OF TEST SCRIPT SUMMARY ~~~~~~~~~~~~~~~"
	return $currentTestResult
}

function Collect-CustomLogFile {
	<#
	.Synopsis
		Checks if log file is present in VM and downloads it if so.
	#>
	param (
		[string]$LogsDestination,
		[string]$PublicIP,
		[string]$SSHPort,
		[string]$Username,
		[string]$Password,
		[string]$FileName
	)
	if (Check-FileInLinuxGuest -ipv4 $PublicIP -vmPassword $Password -vmPort $SSHPort -vmUserName $Username -fileName $FileName) {
		Copy-RemoteFiles -download -downloadFrom $PublicIP -files $FileName `
			-downloadTo $LogsDestination -port $SSHPort -username $Username -password $Password
	}
	else {
		Write-LogWarn "${fileName} does not exist on VM."
	}
}

Function Compare-OsLogs($InitialLogFilePath, $FinalLogFilePath, $LogStatusFilePath, $ErrorMatchPatten) {
	$retValue = $true
	try {
		$initialLogs = Get-Content $InitialLogFilePath
		$finalLogs = Get-Content $FinalLogFilePath

		if (-not $initialLogs) {
			if (-not $finalLogs) {
				Write-LogInfo "Initial and final logs are both empty"
				return $true
			}
			else {
				$initialLogs = @("This is a dummy log for object comparison")
			}
		}
		elseif (-not $finalLogs) {
			Write-LogInfo "Final log is empty"
			return $true
		}
		$fileDiff = Compare-Object -ReferenceObject $initialLogs -DifferenceObject $finalLogs

		if (!$fileDiff) {
			$msg = "Initial and Final Logs have same content"
			Write-LogInfo $msg
			Set-Content -Value $msg -Path $LogStatusFilePath
		}
		else {
			$errorCount = 0
			$msg = "Following lines were added in the logs during execution of test."
			$patternStr = $ErrorMatchPatten.Replace('|', '/')
			Set-Content -Value $msg -Path $LogStatusFilePath
			Add-Content -Value "-------------------------------START----------------------------------" -Path $LogStatusFilePath
			foreach ($line in $fileDiff) {
				if ($line.SideIndicator -eq "=>") {
					Add-Content -Value $line.InputObject -Path $LogStatusFilePath
					if ($line.InputObject -imatch $ErrorMatchPatten) {
						$errorCount += 1
						if ($errorCount -eq 1) {
							$warnMsg = "Following $patternStr messages were added in the logs during execution of test:"
							Write-LogWarn $warnMsg
						}
						Write-LogWarn $line.InputObject
					}
				}
			}
			Add-Content -Value "--------------------------------EOF-----------------------------------" -Path $LogStatusFilePath
			if ($errorCount -gt 0) {
				Write-LogWarn "Found $errorCount $patternStr messages in the logs during execution."
				$retValue = $false
			}
		}
	}
	catch {
		$line = $_.InvocationInfo.ScriptLineNumber
		$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
		$ErrorMessage = $_.Exception.Message
		Write-LogErr "EXCEPTION: $ErrorMessage"
		Write-LogErr "Calling function - $($MyInvocation.MyCommand)."
		Write-LogErr "Source: Line $line in script $script_name."
	}
	return $retValue
}


Function Check-KernelLogs($allVMData, $vmUser, $vmPassword) {
	try {
		$errorLines = @()
		$errorLines += "Call Trace"
		$errorLines += "rcu_sched self-detected stall on CPU"
		$errorLines += "rcu_sched detected stalls on"
		$errorLines += "BUG: soft lockup"
		$totalErrors = 0
		if ( !$vmUser ) {
			$vmUser = $user
		}
		if ( !$vmPassword ) {
			$vmPassword = $password
		}
		$retValue = $false
		foreach ($VM in $allVMData) {
			$vmErrors = 0
			$BootLogDir = "$Logdir\$($VM.RoleName)"
			mkdir $BootLogDir -Force | Out-Null
			Write-LogInfo "Collecting $($VM.RoleName) VM Kernel Logs.."
			$currentKernelLogFile = "$BootLogDir\CurrentKernelLogs.txt"
			$Null = Run-LinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > ./CurrentKernelLogs.txt" -runAsSudo
			$Null = Copy-RemoteFiles -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "./CurrentKernelLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
			Write-LogInfo "$($VM.RoleName): Kernel logs collected successfully."
			foreach ($errorLine in $errorLines) {
				Write-LogInfo "Checking for $errorLine in kernel logs.."
				$KernelLogs = Get-Content $currentKernelLogFile
				foreach ( $line in $KernelLogs ) {
					if ( ($line -imatch "$errorLine") -and ($line -inotmatch "initcall ")) {
						Write-LogErr $line
						$totalErrors += 1
						$vmErrors += 1
					}
					if ( $line -imatch "\[<") {
						Write-LogErr $line
					}
				}
			}
			if ( $vmErrors -eq 0 ) {
				Write-LogInfo "$($VM.RoleName) : No issue found from the kernel logs."
				$retValue = $true
			}
			else {
				Write-LogErr "$($VM.RoleName) : $vmErrors errors found."
				$retValue = $false
			}
		}
		if ( $totalErrors -eq 0 ) {
			$retValue = $true
		}
		else {
			$retValue = $false
		}
	}
	catch {
		$retValue = $false
	}
	return $retValue
}

Function Get-SystemDetailLogs($AllVMData, $User, $Password) {
	foreach ($testVM in $AllVMData) {
		$testIP = $testVM.PublicIP
		$testPort = $testVM.SSHPort
		$LisLogFile = "LIS-Logs" + ".tgz"
		try {
			Write-LogInfo "Collecting logs from IP : $testIP PORT : $testPort"
			Copy-RemoteFiles -upload -uploadTo $testIP -username $User -port $testPort -password $Password -files '.\Testscripts\Linux\CORE-LogCollector.sh'
			Run-LinuxCmd -username $User -password $Password -ip $testIP -port $testPort -command 'chmod +x CORE-LogCollector.sh'
			$out = Run-LinuxCmd -username $User -password $Password -ip $testIP -port $testPort -command './CORE-LogCollector.sh -v' -runAsSudo
			Write-LogInfo $out
			Copy-RemoteFiles -download -downloadFrom $testIP -username $User -password $Password -port $testPort -downloadTo $LogDir -files $LisLogFile
			Write-LogInfo "Logs collected successfully from IP : $testIP PORT : $testPort"
			if ($TestPlatform -eq "Azure") {
				Rename-Item -Path "$LogDir\$LisLogFile" -NewName ("LIS-Logs-" + $testVM.RoleName + ".tgz") -Force
			}
		}
		catch {
			$ErrorMessage = $_.Exception.Message
			Write-LogErr "EXCEPTION : $ErrorMessage"
			Write-LogErr "Unable to collect logs from IP : $testIP PORT : $testPort"
		}
	}
}

Function Trim-ErrorLogMessage($text) {
	# Trim, avoid SQL insert syntax error
	$text = ($text -replace "{|}", " ").Replace("'", """")
	return $text + "`r`n"
}
