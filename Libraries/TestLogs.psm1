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
Function Write-Log()
{
	param
	(
		[ValidateSet('INFO','WARN','ERROR', IgnoreCase = $false)]
		[string]$logLevel,
		[string]$text
	)

	if ($password) {
		$text = $text.Replace($password,"******")
	}
	$now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
	$logType = $logLevel.PadRight(5, ' ')
	$finalMessage = "$now : [$logType] $text"
	$fgColor = "White"
	switch ($logLevel)
	{
		"INFO"	{$fgColor = "White"; continue}
		"WARN"	{$fgColor = "Yellow"; continue}
		"ERROR"	{$fgColor = "Red"; continue}
	}
	Write-Host $finalMessage -ForegroundColor $fgColor

	try
	{
		if ($LogDir) {
			if (!(Test-Path $LogDir)) {
				New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
			}
		} else {
			$LogDir = $env:TEMP
		}

		$LogFileFullPath = Join-Path $LogDir $LogFileName
		if (!(Test-Path $LogFileFullPath)) {
			New-Item -path $LogDir -name $LogFileName -type "file" | Out-Null
		}
		Add-Content -Value $finalMessage -Path $LogFileFullPath -Force
	}
	catch
	{
		Write-Output "[LOG FILE EXCEPTION] : $now : $text"
	}
}

Function Write-LogInfo($text)
{
	Write-Log "INFO" $text
}

Function Write-LogErr($text)
{
	Write-Log "ERROR" $text
}

Function Write-LogWarn($text)
{
	Write-Log "WARN" $text
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
							"TestSkipped" = $global:ResultSkipped;
							"TestFailed" = $global:ResultFail;
							"TestAborted" = $global:ResultAborted;
						}

	$currentTestResult = Create-TestResultObject

	if ($TestType -eq "sh") {
		$filesTocopy = "{0}/state.txt, {0}/summary.log, {0}/TestExecution.log, {0}/TestExecutionError.log" `
			-f @("/home/${Username}")
		Copy-RemoteFiles -download -downloadFrom $PublicIP -downloadTo $LogsDestination `
			 -Port $SSHPort -Username $Username -password $Password `
			 -files $filesTocopy
		$summary = Get-Content (Join-Path $LogDir "summary.log")
		$testState = Get-Content (Join-Path $LogDir "state.txt")
		$currentTestResult.TestResult = $resultTranslation[$testState]
	} elseif ($TestType -eq "py") {
		$filesTocopy = "{0}/state.txt, {0}/Summary.log, {0}/${TestName}_summary.log" `
			-f @("/home/${Username}")
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

Function Get-SystemBasicLogs($AllVMData, $User, $Password, $currentTestData, $CurrentTestResult, $enableTelemetry) {
	try
	{
		if ($allVMData.Count -gt 1)
		{
			$vmData = $allVMData[0]
		}
		else
		{
			$vmData = $allVMData
		}
		$FilesToDownload = "$($vmData.RoleName)-*.txt"
		Copy-RemoteFiles -upload -uploadTo $vmData.PublicIP -port $vmData.SSHPort `
			-files .\Testscripts\Linux\CollectLogFile.sh `
			-username $user -password $password -maxRetry 5 | Out-Null
		$Null = Run-LinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort `
			-command "bash CollectLogFile.sh -hostname $($vmData.RoleName)" -ignoreLinuxExitCode -runAsSudo
		$Null = Copy-RemoteFiles -downloadFrom $vmData.PublicIP -port $vmData.SSHPort `
			-username $user -password $password -files "$FilesToDownload" -downloadTo "$LogDir" -download
		$KernelVersion = Get-Content "$LogDir\$($vmData.RoleName)-kernelVersion.txt"
		$GuestDistro = Get-Content "$LogDir\$($vmData.RoleName)-distroVersion.txt"
		$LISMatch = (Select-String -Path "$LogDir\$($vmData.RoleName)-lis.txt" -Pattern "^version:").Line
		if ($LISMatch)
		{
			$LISVersion = $LISMatch.Split(":").Trim()[1]
		}
		else
		{
			$LISVersion = "NA"
		}
		#region Host Version checking
		$FoundLineNumber = (Select-String -Path "$LogDir\$($vmData.RoleName)-dmesg.txt" -Pattern "Hyper-V Host Build").LineNumber
		if (![string]::IsNullOrEmpty($FoundLineNumber)) {
			$ActualLineNumber = $FoundLineNumber[-1] - 1
			$FinalLine = [string]((Get-Content -Path "$LogDir\$($vmData.RoleName)-dmesg.txt")[$ActualLineNumber])
			$FinalLine = $FinalLine.Replace('; Vmbus version:4.0','')
			$FinalLine = $FinalLine.Replace('; Vmbus version:3.0','')
			$HostVersion = ($FinalLine.Split(":")[$FinalLine.Split(":").Count -1 ]).Trim().TrimEnd(";")
		}
		#endregion

		if ($currentTestData.AdditionalHWConfig.Networking -imatch "SRIOV")
		{
			$Networking = "SRIOV"
		}
		else
		{
			$Networking = "Synthetic"
		}
		if ($TestPlatform -eq "Azure")
		{
			$VMSize = $vmData.InstanceSize
		}
		if ( $TestPlatform -eq "HyperV")
		{
			$VMSize = $HyperVInstanceSize
		}
		#endregion
		if ($enableTelemetry) {
			$SQLQuery = Get-SQLQueryOfTelemetryData -TestPlatform $global:TestPlatform -TestLocation $global:TestLocation -TestCategory $CurrentTestData.Category `
			-TestArea $CurrentTestData.Area -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult `
			-ExecutionTag $global:GlobalConfig.$TestPlatform.ResultsDatabase.testTag -GuestDistro $GuestDistro -KernelVersion $KernelVersion `
			-LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -Networking $Networking `
			-ARMImageName $global:ARMImageName -OsVHD $global:BaseOsVHD -BuildURL $env:BUILD_URL

			Upload-TestResultToDatabase -SQLQuery $SQLQuery
		}
	}
	catch
	{
		$line = $_.InvocationInfo.ScriptLineNumber
		$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
		$ErrorMessage =  $_.Exception.Message
		Write-LogErr "EXCEPTION : $ErrorMessage"
		Write-LogErr "Source : Line $line in script $script_name."
		Write-LogErr "Ignorable error in collecting final data from VMs."
	}
}

Function GetAndCheck-KernelLogs($allDeployedVMs, $status, $vmUser, $vmPassword, $EnableCodeCoverage) {
	try	{
		if (!($status -imatch "Initial" -or $status -imatch "Final")) {
			Write-LogInfo "Status value should be either final or initial"
			return $false
		}

		if (!$vmUser) {
			$vmUser = $user
		}
		if (!$vmPassword) {
			$vmPassword = $password
		}

		$retValue = $false
		foreach ($VM in $allDeployedVMs) {
			Write-LogInfo "Collecting $($VM.RoleName) VM Kernel $status Logs..."

			$bootLogDir = "$Logdir\$($VM.RoleName)"
			mkdir $bootLogDir -Force | Out-Null
			$initialBootLogFile = "InitialBootLogs.txt"
			$finalBootLogFile = "FinalBootLogs.txt"
			$initialBootLog = Join-Path $BootLogDir $initialBootLogFile
			$finalBootLog = Join-Path $BootLogDir $finalBootLogFile
			$currenBootLogFile = $initialBootLogFile
			$currenBootLog = $initialBootLog
			$kernelLogStatus = Join-Path $BootLogDir "KernelLogStatus.txt"

			if ($status -imatch "Final") {
				$currenBootLogFile = $finalBootLogFile
				$currenBootLog = $finalBootLog
			}

			if ($status -imatch "Initial") {
				$checkConnectivityFile = Join-Path $LogDir ([System.IO.Path]::GetRandomFileName())
				Set-Content -Value "Test connectivity." -Path $checkConnectivityFile
				Copy-RemoteFiles -uploadTo $VM.PublicIP -port $VM.SSHPort  -files $checkConnectivityFile `
					-username $vmUser -password $vmPassword -upload | Out-Null
				Remove-Item -Path $checkConnectivityFile -Force
			}

			if ($EnableCodeCoverage -and ($status -imatch "Final")) {
				Write-LogInfo "Collecting coverage debug files from VM $($VM.RoleName)"

				$gcovCollected = Collect-GcovData -ip $VM.PublicIP -port $VM.SSHPort `
					-username $vmUser -password $vmPassword -logDir $LogDir

				if ($gcovCollected) {
					Write-LogInfo "GCOV data collected successfully"
				} else {
					Write-LogErr "Failed to collect GCOV data from VM: $($VM.RoleName)"
				}
			}
			Run-LinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -runAsSudo `
				-username $vmUser -password $vmPassword `
				-command "dmesg > /home/$vmUser/${currenBootLogFile}" | Out-Null
			Copy-RemoteFiles -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/${currenBootLogFile}" `
				-downloadTo $BootLogDir -username $vmUser -password $vmPassword | Out-Null
			Write-LogInfo "$($VM.RoleName): $status Kernel logs collected SUCCESSFULLY to ${currenBootLogFile} file."

			Write-LogInfo "Checking for call traces in kernel logs.."
			$KernelLogs = Get-Content $currenBootLog
			$callTraceFound  = $false
			foreach ($line in $KernelLogs) {
				if (( $line -imatch "Call Trace" ) -and ($line -inotmatch "initcall ")) {
					Write-LogErr $line
					$callTraceFound = $true
				}
				if ($callTraceFound) {
					if ($line -imatch "\[<") {
						Write-LogErr $line
					}
				}
			}
			if (!$callTraceFound) {
				Write-LogInfo "No kernel call traces found in the kernel log"
			}

			if ($status -imatch "Initial") {
				if (!$global:detectedDistro) {
					$detectedDistro = Detect-LinuxDistro -VIP $VM.PublicIP -SSHport $VM.SSHPort `
						-testVMUser $vmUser -testVMPassword $vmPassword
				}
				Set-DistroSpecificVariables -detectedDistro $detectedDistro
				$retValue = $true
			}

			if($status -imatch "Final") {
				$KernelDiff = Compare-Object -ReferenceObject (Get-Content $FinalBootLog) `
					-DifferenceObject (Get-Content $InitialBootLog)

				# Removing final dmesg file from logs to reduce the size of logs.
				# We can always see complete Final Logs as: Initial Kernel Logs + Difference in Kernel Logs
				Remove-Item -Path $FinalBootLog -Force | Out-Null

				if (!$KernelDiff) {
					$msg = "Initial and Final Kernel Logs have same content"
					Write-LogInfo $msg
					Set-Content -Value $msg -Path $KernelLogStatus
					$retValue = $true
				} else {
					$errorCount = 0
					$msg = "Following lines were added in the kernel log during execution of test."
					Set-Content -Value $msg -Path $KernelLogStatus
					Add-Content -Value "-------------------------------START----------------------------------" -Path $KernelLogStatus
					foreach ($line in $KernelDiff) {
						Add-Content -Value $line.InputObject -Path $KernelLogStatus
						if ( ($line.InputObject -imatch "fail") -or ($line.InputObject -imatch "error") `
								-or ($line.InputObject -imatch "warning")) {
							$errorCount += 1
							if ($errorCount -eq 1) {
								$warnMsg = "Following fail/error/warning messages were added in the kernel log during execution of test:"
								Write-LogWarn $warnMsg
							}
							Write-LogWarn $line.InputObject
						}
					}
					Add-Content -Value "--------------------------------EOF-----------------------------------" -Path $KernelLogStatus
					if ($errorCount -gt 0) {
						Write-LogWarn "Found $errorCount fail/error/warning messages in kernel logs during execution."
						$retValue = $false
					}
					Write-LogInfo "$($VM.RoleName): $status Kernel logs collected and compared successfully"
				}

				if ($callTraceFound) {
					Write-LogInfo "Preserving the Resource Group(s) $($VM.ResourceGroupName)"
					Add-ResourceGroupTag -ResourceGroup $VM.ResourceGroupName -TagName $preserveKeyword -TagValue "yes"
					Add-ResourceGroupTag -ResourceGroup $VM.ResourceGroupName -TagName "calltrace" -TagValue "yes"
					Write-LogInfo "Setting tags : calltrace = yes; testName = $testName"
					$hash = @{}
					$hash.Add("calltrace","yes")
					$hash.Add("testName","$testName")
					$Null = Set-AzureRmResourceGroup -Name $($VM.ResourceGroupName) -Tag $hash
				}
			}
		}
	} catch {
		Write-LogInfo $_
		$retValue = $false
	}

	return $retValue
}

Function Check-KernelLogs($allVMData, $vmUser, $vmPassword)
{
	try
	{
		$errorLines = @()
		$errorLines += "Call Trace"
		$errorLines += "rcu_sched self-detected stall on CPU"
		$errorLines += "rcu_sched detected stalls on"
		$errorLines += "BUG: soft lockup"
		$totalErrors = 0
		if ( !$vmUser )
		{
			$vmUser = $user
		}
		if ( !$vmPassword )
		{
			$vmPassword = $password
		}
		$retValue = $false
		foreach ($VM in $allVMData)
		{
			$vmErrors = 0
			$BootLogDir="$Logdir\$($VM.RoleName)"
			mkdir $BootLogDir -Force | Out-Null
			Write-LogInfo "Collecting $($VM.RoleName) VM Kernel $status Logs.."
			$currentKernelLogFile="$BootLogDir\CurrentKernelLogs.txt"
			$Null = Run-LinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/CurrentKernelLogs.txt" -runAsSudo
			$Null = Copy-RemoteFiles -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/CurrentKernelLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
			Write-LogInfo "$($VM.RoleName): $status Kernel logs collected ..SUCCESSFULLY"
			foreach ($errorLine in $errorLines)
			{
				Write-LogInfo "Checking for $errorLine in kernel logs.."
				$KernelLogs = Get-Content $currentKernelLogFile
				foreach ( $line in $KernelLogs )
				{
					if ( ($line -imatch "$errorLine") -and ($line -inotmatch "initcall "))
					{
						Write-LogErr $line
						$totalErrors += 1
						$vmErrors += 1
					}
					if ( $line -imatch "\[<")
					{
						Write-LogErr $line
					}
				}
			}
			if ( $vmErrors -eq 0 )
			{
				Write-LogInfo "$($VM.RoleName) : No issues in kernel logs."
				$retValue = $true
			}
			else
			{
				Write-LogErr "$($VM.RoleName) : $vmErrors errors found."
				$retValue = $false
			}
		}
		if ( $totalErrors -eq 0 )
		{
			$retValue = $true
		}
		else
		{
			$retValue = $false
		}
	}
	catch
	{
		$retValue = $false
	}
	return $retValue
}

Function Get-SystemDetailLogs($AllVMData, $User, $Password)
{
	foreach ($testVM in $AllVMData)
	{
		$testIP = $testVM.PublicIP
		$testPort = $testVM.SSHPort
		$LisLogFile = "LIS-Logs" + ".tgz"
		try
		{
			Write-LogInfo "Collecting logs from IP : $testIP PORT : $testPort"
			Copy-RemoteFiles -upload -uploadTo $testIP -username $User -port $testPort -password $Password -files '.\Testscripts\Linux\CORE-LogCollector.sh'
			Run-LinuxCmd -username $User -password $Password -ip $testIP -port $testPort -command 'chmod +x CORE-LogCollector.sh'
			$out = Run-LinuxCmd -username $User -password $Password -ip $testIP -port $testPort -command './CORE-LogCollector.sh -v' -runAsSudo
			Write-LogInfo $out
			Copy-RemoteFiles -download -downloadFrom $testIP -username $User -password $Password -port $testPort -downloadTo $LogDir -files $LisLogFile
			Write-LogInfo "Logs collected successfully from IP : $testIP PORT : $testPort"
			if ($TestPlatform -eq "Azure")
			{
				Rename-Item -Path "$LogDir\$LisLogFile" -NewName ("LIS-Logs-" + $testVM.RoleName + ".tgz") -Force
			}
		}
		catch
		{
			$ErrorMessage =  $_.Exception.Message
			Write-LogErr "EXCEPTION : $ErrorMessage"
			Write-LogErr "Unable to collect logs from IP : $testIP PORT : $testPort"
		}
	}
}
