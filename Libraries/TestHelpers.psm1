##############################################################################################
# TestHelpers.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation.
	This module defines a set of helper functions.

.PARAMETER
	<Parameters>

.INPUTS

.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE

#>
###############################################################################################
Function New-ResultSummary($testResult, $checkValues, $testName, $metaData) {
	if ( $metaData ) {
		$resultString = "	$metaData : $testResult <br />"
	} else {
		$resultString = "	$testResult <br />"
	}
	return $resultString
}

$ExcludedSetupConfigsToDisplay = @("RGIdentifier", "SetupType", "SetupScript","TiPSessionId","TiPCluster","PlatformFaultDomainCount","PlatformUpdateDomainCount")
function ConvertFrom-SetupConfig([object]$SetupConfig, [switch]$WrappingLines) {
	$resultString = ""
	$SetupConfig.ChildNodes | Sort-Object LocalName | Foreach-Object {
		if ($SetupConfig.($_.LocalName) -and !($ExcludedSetupConfigsToDisplay -contains $_.LocalName)) {
			if ($SetupConfig.($_.LocalName).InnerText) {
				$value = $SetupConfig.($_.LocalName).InnerText
			} else {
				$value = $SetupConfig.($_.LocalName)
			}
			if ($WrappingLines.IsPresent) {
				$resultString += "&nbsp;&nbsp;$($_.LocalName):$value<br />"
			}
			else {
				$resultString += "$($_.LocalName): $value, "
			}
		}
	}
	return $resultString.Trim(", ")
}

Function Get-FinalResultHeader($resultArr) {
	switch ($resultArr) {
		{($_ -imatch "FAIL")} { $result = $global:ResultFail; break}
		{($_ -imatch "Abort")} { $result = $global:ResultAborted; break}
		{($_ -imatch "Skip")} { $result = $global:ResultSkipped; break}
		{($_ -imatch "PASS")} { $result = $global:ResultPass; break}
		default { $result = $global:ResultFail }
	}
	return $result
}

function Create-TestResultObject()
{
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name TestResult -Value $null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name TestSummary -Value $null -Force
	# An array of map, which contains column/value data to be inserted to database
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name TestResultData -Value @() -Force
	return $objNode
}

# Upload a single file
function Upload-RemoteFile($uploadTo, $port, $file, $username, $password, $usePrivateKey, $maxRetry) {
	$retry=1
	if (!$maxRetry) {
		$maxRetry = 10
	}
	if ($global:sshPrivateKey) {
		$usePrivateKey = $true
		$sshKey = $global:sshPrivateKey
	}
	while($retry -le $maxRetry) {
		if ($usePrivateKey) {
			Write-LogDbg "Uploading $file to $username : $uploadTo, port $port using PrivateKey authentication"
			Write-Output "y" | .\Tools\pscp -i $sshKey -q -P $port $file $username@${uploadTo}:
			if ($LASTEXITCODE -ne 0) {
				Write-Output "y" | .\Tools\pscp -scp -i $sshKey -q -P $port $file $username@${uploadTo}:
			}
			$returnCode = $LASTEXITCODE
		} else {
			Write-LogDbg "Uploading $file to $username @ $uploadTo : $port using password authentication"
			$curDir = $PWD
			$uploadStatusRandomFileName = "UploadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
			$uploadStatusRandomFile = Join-Path $env:TEMP $uploadStatusRandomFileName
			$uploadStartTime = Get-Date
			$uploadJob = Start-Job -ScriptBlock {
							Set-Location $args[0];
							Write-Output $args;
							Set-Content -Value "1" -Path $args[6];
							$username = $args[4];
							$uploadTo = $args[5];
							Write-Output "yes" | .\Tools\pscp -v -pw $args[1] -q -P $args[2] $args[3] $username@${uploadTo}: 2>&1;
							if ( $LASTEXITCODE -ne 0 ) {
								Write-Output "yes" | .\Tools\pscp -v -scp -pw $args[1] -q -P $args[2] $args[3] $username@${uploadTo}: 2>&1;
							}
							Set-Content -Value $LASTEXITCODE -Path $args[6];
						} -ArgumentList $curDir,$password,$port,$file,$username,${uploadTo},$uploadStatusRandomFile
			Start-Sleep -Milliseconds 100
			$uploadJobStatus = Get-Job -Id $uploadJob.Id
			$uploadTimout = $false
			$pscpStuckTimeout = 90
			while (( $uploadJobStatus.State -eq "Running" ) -and ( !$uploadTimout )) {
				$now = Get-Date
				if (($now - $uploadStartTime).TotalSeconds -gt $pscpStuckTimeout) {
					# We're handling here a very rare condition where VM is open to establish the TCP connection (ping is working)
					# but, VM is not responding to SSH client. This behavior results in permanent hung of SSH client with below logs.
					#     Looking up host "xxx.xxx.xxx.xxx" for SSH connection
					#     Connecting to xxx.xxx.xxx.xxx port 22
					#     We claim version: SSH-2.0-PuTTY_Release_0.71
					#     <No further messages and pscp.exe is stuck here.>
					# To handle this, we added a check to see if the pscp.exe's last console output is matching to "We claim version" string for more than 60 seconds.
					# Because, for any other errors like "connection timeout" or "connection refused" happens under 20 seconds.
					# The string - "We claim version", may change in future depending on the pscp.exe version, but this does not impact the existing flow of this function.
					$uploadJobStatusConsole = [string](Receive-Job -Id $uploadJob.Id 2>&1)
					if ($uploadJobStatusConsole) { $uploadJobStatusConsole = $uploadJobStatusConsole.TrimEnd() }
					if ($uploadJobStatusConsole -and $uploadJobStatusConsole.Split("`n")[-1] -imatch "We claim version") {
						Throw ".\Tools\pscp is stuck for $pscpStuckTimeout seconds. Aborting upload."
					}
				}
				if ( ($now - $uploadStartTime).TotalSeconds -gt 600 ) {
					$uploadTimout = $true
					Write-LogErr "Upload Timout!"
				}
				Start-Sleep -Seconds 1
				$uploadJobStatus = Get-Job -Id $uploadJob.Id
			}
			$returnCode = Get-Content -Path $uploadStatusRandomFile
			Remove-Item -Force $uploadStatusRandomFile | Out-Null
			Remove-Job -Id $uploadJob.Id -Force | Out-Null
		}
		if (($returnCode -ne 0) -and ($retry -ne $maxRetry)) {
			Write-LogWarn "Error in upload, attempt $retry/$maxRetry, retrying"
			Wait-Time -seconds 10
		} elseif (($returnCode -ne 0) -and ($retry -eq $maxRetry)) {
			Write-Output "Error in upload after $retry attempt, hence giving up"
			Throw "Calling function - $($MyInvocation.MyCommand). Error in upload after $retry attempt, hence giving up"
		} elseif ($returnCode -eq 0) {
			Write-LogDbg "Upload successful after $retry attempt"
			break
		}
		$retry += 1
	}
}

# Download a single file
function Download-RemoteFile($downloadFrom, $downloadTo, $port, $file, $username, $password, $usePrivateKey, $maxRetry) {
	$retry=1
	if (!$maxRetry) {
		$maxRetry = 20
	}
	if ($global:sshPrivateKey) {
		$usePrivateKey = $true
		$sshKey = $global:sshPrivateKey
	}
	while($retry -le $maxRetry) {
		if ($usePrivateKey) {
			Write-LogDbg "Downloading $file from $username : $downloadFrom : $port to $downloadTo using PrivateKey authentication"
		} else {
			Write-LogDbg "Downloading $file from $username @ $downloadFrom : $port to $downloadTo using password authentication"
		}
		$curDir = $PWD
		$downloadStatusRandomFileName = "DownloadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
		$downloadStatusRandomFile = Join-Path $env:TEMP $downloadStatusRandomFileName
		Set-Content -Value "1" -Path $downloadStatusRandomFile
		$downloadStartTime = Get-Date

		if ($UsePrivateKey) {
			$downloadJob = Start-Job -ScriptBlock {
				$curDir=$args[0];
				$sshKey=$args[1];
				$port=$args[2];
				$testFile=$args[3];
				$username=$args[4];
				${downloadFrom}=$args[5];
				$downloadTo=$args[6];
				$downloadStatusRandomFile=$args[7];
				Set-Location $curDir;
				Write-Output "y" | .\Tools\pscp.exe -2 -unsafe -i $sshKey -q -P $port $username@${downloadFrom}:$testFile $downloadTo 2> $downloadStatusRandomFile;
				if ($LASTEXITCODE -ne 0) {
					Write-Output "y" | .\Tools\pscp.exe -2 -v -scp -unsafe -i $sshKey -q -P $port $username@${downloadFrom}:$testFile $downloadTo 2> $downloadStatusRandomFile;
				}
				Add-Content -Value "DownloadExitCode_$LASTEXITCODE" -Path $downloadStatusRandomFile;
			} -ArgumentList $curDir,$sshKey,$port,$file,$username,${downloadFrom},$downloadTo,$downloadStatusRandomFile
		} else {
			$downloadJob = Start-Job -ScriptBlock {
				$curDir=$args[0];
				$password=$args[1];
				$port=$args[2];
				$testFile=$args[3];
				$username=$args[4];
				${downloadFrom}=$args[5];
				$downloadTo=$args[6];
				$downloadStatusRandomFile=$args[7];
				Set-Location $curDir;
				Write-Output "yes" | .\Tools\pscp.exe -2 -unsafe -pw $password -q -P $port $username@${downloadFrom}:$testFile $downloadTo 2> $downloadStatusRandomFile;
				if ( $LASTEXITCODE -ne 0 ) {
					Write-Output "yes" | .\Tools\pscp.exe -2 -v -scp -unsafe -pw $password -q -P $port $username@${downloadFrom}:$testFile $downloadTo 2> $downloadStatusRandomFile;
				}
				Add-Content -Value "DownloadExitCode_$LASTEXITCODE" -Path $downloadStatusRandomFile;
			} -ArgumentList $curDir,$password,$port,$file,$username,${downloadFrom},$downloadTo,$downloadStatusRandomFile
		}
		Start-Sleep -Milliseconds 100
		$downloadJobStatus = Get-Job -Id $downloadJob.Id
		$downloadTimout = $false
		while (( $downloadJobStatus.State -eq "Running" ) -and ( !$downloadTimout )) {
			$now = Get-Date
			if ( ($now - $downloadStartTime).TotalSeconds -gt 600 ) {
				$downloadTimout = $true
				Write-LogErr "Download Timout!"
			}
			Start-Sleep -Seconds 1
			$downloadJobStatus = Get-Job -Id $downloadJob.Id
		}
		$downloadExitCode = (Select-String -Path $downloadStatusRandomFile -Pattern "DownloadExitCode_").Line
		if ( $downloadExitCode ) {
			$returnCode = $downloadExitCode.Replace("DownloadExitCode_",'')
		}
		if ( $returnCode -eq 0) {
			Write-LogDbg "Download command returned exit code 0"
		} else {
			$receivedFiles = Select-String -Path "$downloadStatusRandomFile" -Pattern "Sending file"
			if ($receivedFiles.Count -ge 1) {
				Write-LogDbg "Received $($receivedFiles.Count) file(s)"
				$returnCode = 0
			} else {
				Write-LogDbg "Download command returned exit code $returnCode"
				Write-LogDbg "$(Get-Content -Path $downloadStatusRandomFile)"
			}
		}
		Remove-Item -Force $downloadStatusRandomFile | Out-Null
		Remove-Job -Id $downloadJob.Id -Force | Out-Null

		if (($returnCode -ne 0) -and ($retry -ne $maxRetry)) {
			Write-LogWarn "Download error, attempt $retry. Retrying for download"
		} elseif (($returnCode -ne 0) -and ($retry -eq $maxRetry)) {
			Write-Output "Download error after $retry attempt, hence giving up"
			Throw "Calling function - $($MyInvocation.MyCommand). Download error after $retry attempt, hence giving up."
		} elseif ($returnCode -eq 0) {
			Write-LogDbg "Download successful after $retry attempt"
			break
		}
		$retry += 1
	}
}

# Upload or download files to/from remote VMs
Function Copy-RemoteFiles($uploadTo, $downloadFrom, $downloadTo, $port, $files, $username, $password, [switch]$upload, [switch]$download, [switch]$usePrivateKey, [switch]$doNotCompress, $maxRetry) {
	if ($global:IsWindowsImage) {
		Write-LogDbg "It is a Windows VM. Skip Copy-RemoteFiles."
		return
	}
	if (!$files) {
		Write-LogErr "No file(s) to copy."
		return
	}
	$fileList = @()
	foreach ($f in $files.Split(",")) {
		if ($f) {
			$file = $f.Trim()
			if ($file.EndsWith(".sh") -or $file.EndsWith(".py")) {
				$out = .\Tools\dos2unix.exe $file 2>&1
				Write-LogDbg ([string]$out)
			}
			$fileList += $file
		}
	}
	if ($upload) {
		$doCompress = ($fileList.Count -gt 2) -and !$doNotCompress
		if ($doCompress) {
			$tarFileName = ($uploadTo+"@"+$port).Replace(".","-")+".tar"
			foreach ($f in $fileList) {
				Write-LogDbg "Compressing $f and adding to $tarFileName"
				$CompressFile = .\Tools\7za.exe a $tarFileName $f
				if ( ! $CompressFile -imatch "Everything is Ok" ) {
					Remove-Item -Path $tarFileName -Force 2>&1 | Out-Null
					Throw "Calling function - $($MyInvocation.MyCommand). Failed to compress $f"
				}
			}
			$fileList = @($tarFileName)
		}
		foreach ($file in $fileList) {
			Upload-RemoteFile -uploadTo $uploadTo -port $port -file $file -username $username -password $password -UsePrivateKey $UsePrivateKey $maxRetry
		}
		if ($doCompress) {
			Write-LogDbg "Removing compressed file : $tarFileName"
			Remove-Item -Path $tarFileName -Force 2>&1 | Out-Null
			Write-LogDbg "Decompressing files in VM ..."
			$out = Run-LinuxCmd -username $username -password $password -ip $uploadTo -port $port -command "tar -xf $tarFileName" -runAsSudo
		}
	} elseif ($download) {
		foreach ($file in $fileList) {
			Download-RemoteFile -downloadFrom $downloadFrom -downloadTo $downloadTo -port $port -file $file -username $username `
				-password $password -usePrivateKey $usePrivateKey $maxRetry
		}
	} else {
		Write-LogErr "Upload/Download switch is not used!"
	}
}

Function Wrap-CommandsToFile([string] $username,[string] $password,[string] $ip,[string] $command, [int] $port)
{
	if ( ( $lastLinuxCmd -eq $command) -and ($lastIP -eq $ip) -and ($lastPort -eq $port) `
		-and ($lastUser -eq $username) -and ($TestPlatform -eq "Azure")) {
		#Skip upload if current command is same as last command.
	} else {
		Set-Variable -Name lastLinuxCmd -Value $command -Scope Global
		Set-Variable -Name lastIP -Value $ip -Scope Global
		Set-Variable -Name lastPort -Value $port -Scope Global
		Set-Variable -Name lastUser -Value $username -Scope Global
		$fileName = "runtest-${global:TestID}.sh"
		$command | out-file -encoding ASCII -filepath "$LogDir\$fileName"
		Copy-RemoteFiles -upload -uploadTo $ip -username $username -port $port -password $password -files "$LogDir\$fileName"
		Remove-Item "$LogDir\$fileName"
	}
}

Function Get-AvailableExecutionFolder([string] $username, [string] $password, [string] $ip, [int] $port) {
	if ("root" -ne $username) {
		Write-LogInfo "Check if execution folder /home/$username exists or not, if not, create one."
		if ($global:sshPrivateKey) {
			$sshKey = $global:sshPrivateKey
			$output = Write-Output "y" | .\Tools\plink.exe -C -i $sshKey -P $port "$username@$ip" "sudo -S bash -c 'if [ ! -d /home/$username ]; then mkdir -p /home/$username; chown -R ${user}: /home/$username; fi; if [ -d /home/$username ]; then echo EXIST; else echo NOTEXIST; fi;'" 2> $null
		} else {
			$output = Write-Output "yes" | .\Tools\plink.exe -C -pw $password -P $port "$username@$ip" "sudo -S bash -c 'if [ ! -d /home/$username ]; then mkdir -p /home/$username; chown -R ${user}: /home/$username; fi; if [ -d /home/$username ]; then echo EXIST; else echo NOTEXIST; fi;'" 2> $null
		}
		if ("NOTEXIST" -eq $output) {
			Write-LogDbg "We can't find or create execution folder /home/$username."
			Throw "Not find available execution folder."
		} else {
			Write-LogDbg "Execution folder /home/$username exists."
			Set-Variable -Name AvailableExecutionFolder -Value $true -Scope Global
		}
	}
}

Function Run-LinuxCmd([string] $username, [string] $password, [string] $ip, [string] $command, [int] $port, [switch]$runAsSudo, [Boolean]$WriteHostOnly, [Boolean]$NoLogsPlease, [switch]$ignoreLinuxExitCode, [int]$runMaxAllowedTime = 300, [switch]$RunInBackGround, [int]$maxRetryCount = 20, [string] $MaskStrings) {
	if ($global:IsWindowsImage) {
		Write-LogDbg "It is a Windows VM. Skip Run-LinuxCmd."
		return
	}
	if (!$global:AvailableExecutionFolder) {
		Get-AvailableExecutionFolder $username $password $ip $port
	}
	Wrap-CommandsToFile $username $password $ip $command $port
	$MaskedCommand = $command
	if ($MaskStrings) {
		foreach ($item in $MaskStrings.Split(",")) {
			if ($item) { $MaskedCommand = $MaskedCommand.Replace($item,'*******') }
		}
	}
	$randomFileName = [System.IO.Path]::GetRandomFileName()
	if ( $maxRetryCount -eq 0) {
		$maxRetryCount = 1
	}
	$currentDir = $PWD.Path
	$RunStartTime = Get-Date
	$scriptName = "runtest-${global:TestID}.sh"

	if ($global:sshPrivateKey) {
		$sshKey = $global:sshPrivateKey
	}
	if ($runAsSudo) {
		$plainTextPassword = $password.Replace('"','');
		if ($detectedDistro -eq "COREOS") {
			$linuxCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && "
			if (!$global:SSHPrivateKey) {
				$linuxCommand += "echo $plainTextPassword | "
			}
			$linuxCommand += "sudo -S env `"PATH=`$PATH`" "
			$logCommand = $linuxCommand
			$linuxCommand += "bash -c `'bash $scriptName ; echo AZURE-LINUX-EXIT-CODE-`$?`' `""
			$logCommand += " $MaskedCommand`""
		} else {
			$linuxCommand = "`""
			if (!$global:SSHPrivateKey) {
				$linuxCommand += "echo $plainTextPassword | "
			}
			$logCommand = $linuxCommand
			$linuxCommand += "sudo -S bash -c `'bash $scriptName ; echo AZURE-LINUX-EXIT-CODE-`$?`' `""
			$logCommand += "sudo -S $MaskedCommand`""
		}
	} else {
		if ($detectedDistro -eq "COREOS") {
			$linuxCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && bash -c `'bash $scriptName ; echo AZURE-LINUX-EXIT-CODE-`$?`' `""
			$logCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && $MaskedCommand`""
		} else {
			$linuxCommand = "`"bash -c `'bash $scriptName ; echo AZURE-LINUX-EXIT-CODE-`$?`' `""
			$logCommand = "`"$MaskedCommand`""
		}
	}
	if ($global:sshPrivateKey) {
		Write-LogDbg ".\Tools\plink.exe -ssh -t -i ppkfile -P $port $username@$ip $logCommand"
	} else {
		Write-LogDbg ".\Tools\plink.exe -ssh -t -pw $password -P $port $username@$ip $logCommand"
	}
	$returnCode = 1
	$attemptswt = 0
	$attemptswot = 0
	$notExceededTimeLimit = $true
	$isBackGroundProcessStarted = $false

	while ( ($returnCode -ne 0) -and ($attemptswt -lt $maxRetryCount -or $attemptswot -lt $maxRetryCount) -and $notExceededTimeLimit) {
		if ($runwithoutt -or $attemptswt -eq $maxRetryCount) {
			Set-Variable -Name runwithoutt -Value true -Scope Global
			$attemptswot +=1
			$runLinuxCmdJob = Start-Job -ScriptBlock `
			{ `
				$username = $args[1]; $password = $args[2]; $ip = $args[3]; $port = $args[4]; $jcommand = $args[5]; $sshKey = $args[6];`
				Set-Location $args[0]; `
				if ($sshKey) { .\Tools\plink.exe -ssh -C -v -i $sshKey -P $port $username@$ip $jcommand; } `
				else { .\Tools\plink.exe -ssh -C -v -pw $password -P $port $username@$ip $jcommand; } `
			} `
			-ArgumentList $currentDir, $username, $password, $ip, $port, $linuxCommand, $sshKey
		} else {
			$attemptswt += 1
			$runLinuxCmdJob = Start-Job -ScriptBlock `
			{ `
				$username = $args[1]; $password = $args[2]; $ip = $args[3]; $port = $args[4]; $jcommand = $args[5]; $sshKey = $args[6];`
				Set-Location $args[0]; `
				if ($sshKey) { .\Tools\plink.exe -ssh -t -C -v -i $sshKey -P $port $username@$ip $jcommand; } `
				else { .\Tools\plink.exe -ssh -t -C -v -pw $password -P $port $username@$ip $jcommand; } `
			} `
			-ArgumentList $currentDir, $username, $password, $ip, $port, $linuxCommand, $sshKey
		}
		$RunLinuxCmdOutput = ""
		$debugOutput = ""
		$LinuxExitCode = ""
		if ( $RunInBackGround ) {
			While(($runLinuxCmdJob.State -eq "Running") -and ($isBackGroundProcessStarted -eq $false ) -and $notExceededTimeLimit) {
				$SSHOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
				$jobOut = Get-Content $LogDir\$randomFileName
				if ($jobOut) {
					foreach($outLine in $jobOut) {
						if ($outLine -imatch "Started a shell") {
							$LinuxExitCode = $outLine
							$isBackGroundProcessStarted = $true
							$returnCode = 0
						} else {
							$RunLinuxCmdOutput += "$outLine`n"
						}
					}
				}
				$debugLines = Get-Content $LogDir\$randomFileName
				if ($debugLines) {
					$debugString = ""
					foreach ($line in $debugLines) {
						$debugString += $line
					}
					$debugOutput += "$debugString`n"
				}
				Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Initiating command in Background Mode : $logCommand on $ip : $port" `
					-Status "Timeout in $($RunMaxAllowedTime - $RunElaplsedTime) seconds.." -Id 87678 `
					-PercentComplete (($RunElaplsedTime/$RunMaxAllowedTime)*100) -CurrentOperation "SSH ACTIVITY : $debugString"
				$RunCurrentTime = Get-Date
				$RunDiffTime = $RunCurrentTime - $RunStartTime
				$RunElaplsedTime =  $RunDiffTime.TotalSeconds
				if ($RunElaplsedTime -le $RunMaxAllowedTime) {
					$notExceededTimeLimit = $true
				} else {
					$notExceededTimeLimit = $false
					Stop-Job $runLinuxCmdJob
					$timeOut = $true
				}
			}
			Wait-Time -seconds 2
			$SSHOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
			if ($SSHOut) {
				foreach ($outLine in $SSHOut) {
					if ($outLine -imatch "AZURE-LINUX-EXIT-CODE-") {
						$LinuxExitCode = $outLine
						$isBackGroundProcessTerminated = $true
					} else {
						$RunLinuxCmdOutput += "$outLine`n"
					}
				}
			}

			$debugLines = Get-Content $LogDir\$randomFileName
			if ($debugLines) {
				$debugString = ""
				foreach ($line in $debugLines) {
					$debugString += $line
				}
				$debugOutput += "$debugString`n"
			}
			Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" `
				-Status $runLinuxCmdJob.State -Id 87678 -SecondsRemaining ($RunMaxAllowedTime - $RunElaplsedTime) -Completed
			if ( $isBackGroundProcessStarted -and !$isBackGroundProcessTerminated ) {
				Write-LogDbg "$MaskedCommand is running in background with ID $($runLinuxCmdJob.Id) ..."
				Add-Content -Path $LogDir\CurrentTestBackgroundJobs.txt -Value $runLinuxCmdJob.Id
				$retValue = $runLinuxCmdJob.Id
			} else {
				Remove-Job $runLinuxCmdJob
				if (!$isBackGroundProcessStarted) {
					Write-LogErr "Failed to start process in background.."
				}
				if ( $isBackGroundProcessTerminated ) {
					Write-LogErr "Background Process terminated from Linux side with error code :  $($LinuxExitCode.Split("-")[4])"
					$returnCode = $($LinuxExitCode.Split("-")[4])
					Write-LogErr $SSHOut
				}
				if ($debugOutput -imatch "Unable to authenticate") {
					Write-LogErr "Unable to authenticate. Not retrying!"
					Throw "Calling function - $($MyInvocation.MyCommand). Unable to authenticate"
				}
				if ($timeOut) {
					$retValue = ""
					Throw "Calling function - $($MyInvocation.MyCommand). Timeout while executing command : $MaskedCommand"
				}
				Write-LogErr "Linux machine returned exit code : $($LinuxExitCode.Split("-")[4])"
				if ($attempts -eq $maxRetryCount) {
					Throw "Calling function - $($MyInvocation.MyCommand). Failed to execute : $MaskedCommand."
				} else {
					if ($notExceededTimeLimit) {
						Write-LogWarn "Failed to execute : $MaskedCommand. Retrying..."
					}
				}
			}
			Remove-Item $LogDir\$randomFileName -Force | Out-Null
		} else {
			While($notExceededTimeLimit -and ($runLinuxCmdJob.State -eq "Running")) {
				$jobOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
				if ($jobOut) {
					$jobOut = $jobOut.Replace("[sudo] password for $username`: ","").Replace("Password: ","")
					foreach ($outLine in $jobOut) {
						if ($outLine -imatch "AZURE-LINUX-EXIT-CODE-") {
							$LinuxExitCode = $outLine
						} else {
							$RunLinuxCmdOutput += "$outLine`n"
						}
					}
				}
				$debugLines = Get-Content $LogDir\$randomFileName
				if ($debugLines) {
					$debugString = ""
					foreach ($line in $debugLines) {
						$debugString += $line
					}
					$debugOutput += "$debugString`n"
				}
				Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" `
					-Status "Timeout in $($RunMaxAllowedTime - $RunElaplsedTime) seconds.." -Id 87678 `
					-PercentComplete (($RunElaplsedTime/$RunMaxAllowedTime)*100) -CurrentOperation "SSH ACTIVITY : $debugString"
				$RunCurrentTime = Get-Date
				$RunDiffTime = $RunCurrentTime - $RunStartTime
				$RunElaplsedTime =  $RunDiffTime.TotalSeconds
				if ($RunElaplsedTime -le $RunMaxAllowedTime) {
					$notExceededTimeLimit = $true
				} else {
					$notExceededTimeLimit = $false
					Stop-Job $runLinuxCmdJob
					$timeOut = $true
				}
			}
			$jobOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
			if ($jobOut) {
				$jobOut = $jobOut.Replace("[sudo] password for $username`: ","").Replace("Password: ","")
				foreach ($outLine in $jobOut) {
					if ($outLine -imatch "AZURE-LINUX-EXIT-CODE-") {
						$LinuxExitCode = $outLine
					} else {
						$RunLinuxCmdOutput += "$outLine`n"
					}
				}
			}
			$debugLines = Get-Content $LogDir\$randomFileName
			if ($debugLines) {
				$debugString = ""
				foreach ($line in $debugLines) {
					$debugString += $line
				}
				$debugOutput += "$debugString`n"
			}
			Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" `
				-Status $runLinuxCmdJob.State -Id 87678 -SecondsRemaining ($RunMaxAllowedTime - $RunElaplsedTime) -Completed
			Remove-Job $runLinuxCmdJob
			Remove-Item $LogDir\$randomFileName -Force | Out-Null
			if ($LinuxExitCode -imatch "AZURE-LINUX-EXIT-CODE-0") {
				$returnCode = 0
				Write-LogDbg "$MaskedCommand executed successfully in $([math]::Round($RunElaplsedTime,2)) seconds." `
					-WriteHostOnly $WriteHostOnly -NoLogsPlease $NoLogsPlease
				$retValue = $RunLinuxCmdOutput.Trim()
			} else {
				if (!$ignoreLinuxExitCode) {
					$debugOutput = ($debugOutput.Split("`n")).Trim()
					foreach ($line in $debugOutput) {
						if ($line) {
							Write-LogErr $line
						}
					}
				}
				if ($debugOutput -imatch "Unable to authenticate") {
						Write-LogWarn "Unable to authenticate. Not retrying!"
						Throw "Calling function - $($MyInvocation.MyCommand). Unable to authenticate"
					}
				if (!$ignoreLinuxExitCode) {
					if ($timeOut) {
						$retValue = ""
						Throw "Calling function - $($MyInvocation.MyCommand). Timeout while executing command : $MaskedCommand"
					}
					Write-LogErr "Linux machine returned exit code : $($LinuxExitCode.Split("-")[4])"
					if ($attemptswt -eq $maxRetryCount -and $attemptswot -eq $maxRetryCount) {
						Throw "Calling function - $($MyInvocation.MyCommand). Failed to execute : $MaskedCommand."
					} else {
						if ($notExceededTimeLimit) {
							Write-LogErr "Failed to execute : $MaskedCommand. Retrying..."
						}
					}
				} else {
					Write-LogDbg "Command execution returned return code $($LinuxExitCode.Split("-")[4]) Ignoring.."
					$retValue = $RunLinuxCmdOutput.Trim()
					break
				}
			}
		}
	}
	return $retValue
}

Function New-TestID() {
	return "{0}{1}" -f $(-join ((65..90) | Get-Random -Count 2 | ForEach-Object {[char]$_})), $(Get-Random -Maximum 99 -Minimum 11)
}

Function New-TimeBasedUniqueId() {
	return Get-Date -UFormat "%Y%m%d%H%M%S"
}

Function Raise-Exception($Exception) {
	try {
		$line = $Exception.InvocationInfo.ScriptLineNumber
		$script_name = ($Exception.InvocationInfo.ScriptName).Replace($PWD,".")
		$ErrorMessage =  $Exception.Exception.Message
	} catch {
		Write-LogErr "Failed to display Exception"
	} finally {
		$now = [Datetime]::Now.ToUniversalTime().ToString("MM/dd/yyyy HH:mm:ss")
		Write-Host "$now : [OOPS   ]: $ErrorMessage"  -ForegroundColor Red
		Write-Host "$now : [SOURCE ]: Line $line in script $script_name."  -ForegroundColor Red
		Throw "Calling function - $($MyInvocation.MyCommand)"
	}
}

Function Set-DistroSpecificVariables($detectedDistro) {
	Set-Variable -Name ifconfig_cmd -Value "ifconfig" -Scope Global
	if (($detectedDistro -eq "SLES") -or ($detectedDistro -eq "SUSE")) {
		Set-Variable -Name ifconfig_cmd -Value "/sbin/ifconfig" -Scope Global
		Set-Variable -Name fdisk -Value "/sbin/fdisk" -Scope Global
		Write-LogDbg "Set `$ifconfig_cmd > $ifconfig_cmd for $detectedDistro"
		Write-LogDbg "Set `$fdisk > /sbin/fdisk for $detectedDistro"
	} else {
		Set-Variable -Name fdisk -Value "fdisk" -Scope Global
		Write-LogDbg "Set `$fdisk > fdisk for $detectedDistro"
	}
}

Function Test-TCP([string]$testIP, [Int32]$testport) {
	$socket = New-Object Net.Sockets.TcpClient
	$isConnected = "False"
	try {
		$socket.Connect($testIP, $testPort)
	} catch {
		Write-LogWarn "TCP test failed"
	}
	if ($socket.Connected) {
		$isConnected = "True"
	}
	$socket.Close()
	return $isConnected
}

Function Retry-Operation($operation, $description, $expectResult=$null, $maxRetryCount=10, $retryInterval=10, [switch]$NoLogsPlease, [switch]$ThrowExceptionOnFailure) {
	$retryCount = 1

	do {
		Write-LogDbg "Attempt : $retryCount/$maxRetryCount : $description" -NoLogsPlease $NoLogsPlease
		$ret = $null
		$oldErrorActionValue = $ErrorActionPreference
		$ErrorActionPreference = "Stop"

		try {
			$ret = Invoke-Command -ScriptBlock $operation
			if ($null -ne $expectResult) {
				if ($ret -match $expectResult) {
					return $ret
				} else {
					$ErrorActionPreference = $oldErrorActionValue
					$retryCount ++
					Wait-Time -seconds $retryInterval
				}
			} else {
				return $ret
			}
		} catch {
			$retryCount ++
			Wait-Time -seconds $retryInterval
			if ( $retryCount -le $maxRetryCount ) {
				continue
			}
		} finally {
			$ErrorActionPreference = $oldErrorActionValue
		}
		if ($retryCount -ge $maxRetryCount) {
			Write-LogErr "Command '$operation' Failed."
			break;
		}
	} while ($True)

	if ($ThrowExceptionOnFailure) {
		Raise-Exception -Exception "Command '$operation' Failed."
	} else {
		return $null
	}
}

function New-ZipFile( $zipFileName, $sourceDir ) {
	Write-LogDbg "Creating '$zipFileName' from '$sourceDir'"
	$currentDir = (Get-Location).Path
	$7z = (Get-ChildItem .\Tools\7za.exe).FullName
	$sourceDir = $sourceDir.Trim('\')
	Set-Location $sourceDir
	$out = Invoke-Expression "$7z a -mx5 $zipFileName * -r"
	Set-Location $currentDir
	if ($out -match "Everything is Ok") {
		Write-LogDbg "$zipFileName created successfully."
	} else {
		Write-LogErr "Unexpected output from 7za.exe when creating $zipFileName :"
		Write-LogErr $out
	}
}

Function Get-LISAv2Tools($XMLSecretFile) {
	# Copy required binary files to working folder
	$CurrentDirectory = Get-Location
	$CmdArray = @('7za.exe','dos2unix.exe','gawk','jq','plink.exe','pscp.exe', `
					'kvp_client32','kvp_client64','nc.exe','lz4.exe','sbinfo')

	if ($XMLSecretFile) {
		$WebClient = New-Object System.Net.WebClient
		$xmlSecret = [xml](Get-Content $XMLSecretFile)
		$toolFileAccessLocation = $xmlSecret.secrets.blobStorageLocation
		Write-LogInfo "Refreshed Blob Storage Location information, $toolFileAccessLocation"
	}

	$CmdArray | ForEach-Object {
		# Verify the binary file in Tools location
		if (! (Test-Path $CurrentDirectory/Tools/$_) ) {
			Write-LogWarn "$_ file is not found in Tools folder."
			if ($toolFileAccessLocation) {
				$downloadFileError = $False
				try {
					$WebClient.DownloadFile("$toolFileAccessLocation/$_","$CurrentDirectory\Tools\$_")
				}
				catch {
					$downloadFileError = $True
				}
				if ($downloadFileError) {
					Write-LogWarn "Failed to download '$_', please make sure it's available from '$toolFileAccessLocation'"
				}
				else {
					Write-LogInfo "File $_ successfully downloaded in Tools folder: $CurrentDirectory\Tools."
				}
			} else {
				Throw "$_ file is not found, please either download the file to Tools folder, or specify the blobStorageLocation in XMLSecretFile"
			}
		}
	}
}

Function Get-SSHKey ($XMLSecretFile) {
	# Download SSHKey when provide a URL
	$temp_Folder = $env:TEMP
	$sshKeyPath = [string]::Empty
	if ($XMLSecretFile) {
		$WebClient = New-Object System.Net.WebClient
		$xmlSecret = [xml](Get-Content $XMLSecretFile)
		$privateSSHKey = if ($xmlSecret.secrets.sshPrivateKey.InnerText) { $xmlSecret.secrets.sshPrivateKey.InnerText } else { $xmlSecret.secrets.sshPrivateKey }
		if ($privateSSHKey) {
			$sshKeyPath = $privateSSHKey
		}
	}
	if ($privateSSHKey) {
		if ($privateSSHKey -match "^(http|https)://") {
			$WebClient = New-Object System.Net.WebClient
			$privateSSHKeyName = $privateSSHKey.Split('?')[0].Split('/')[-1]
			try {
				$WebClient.DownloadFile("$privateSSHKey", "$temp_Folder/$privateSSHKeyName")
			} catch {
				Throw "Failed to download from $privateSSHKey, please double check the path."
			}
			$sshKeyPath = "$temp_Folder/$privateSSHKeyName"
		}
		if (![System.IO.File]::Exists($sshKeyPath)) {
			Throw "SSH Private key $sshKeyPath doesn't exist, please double check."
		}
		$sshKeyPath = (Resolve-Path $sshKeyPath).Path
		if ($sshKeyPath -notmatch ".ppk$") {
			Throw "Only support .ppk format."
		}
	}
	return $sshKeyPath
}

function Create-ConstantsFile {
	<#
	.DESCRIPTION
	Generic function that creates the constants.sh file using a hashtable
	#>

	param(
		[string]$FilePath,
		[hashtable]$Parameters
	)

	Set-Content -Value "#Generated by LISAv2" -Path $FilePath -Force
	foreach ($param in $Parameters.Keys) {
		Add-Content -Value ("{0}={1}" `
				-f @($param,$($Parameters[$param]))) -Path $FilePath -Force
		$msg = ("{0}={1} added to constants.sh file" `
				-f @($param,$($Parameters[$param])))
		Write-LogDbg $msg
	}
}

Function Validate-VHD($vhdPath) {
	try {
		$tempVHDName = Split-Path $vhdPath -leaf
		Write-LogDbg "Inspecting '$tempVHDName'. Please wait..."
		$VHDInfo = Get-VHD -Path $vhdPath -ErrorAction Stop
		Write-LogDbg "  VhdFormat            :$($VHDInfo.VhdFormat)"
		Write-LogDbg "  VhdType              :$($VHDInfo.VhdType)"
		Write-LogDbg "  FileSize             :$($VHDInfo.FileSize)"
		Write-LogDbg "  Size                 :$($VHDInfo.Size)"
		Write-LogDbg "  LogicalSectorSize    :$($VHDInfo.LogicalSectorSize)"
		Write-LogDbg "  PhysicalSectorSize   :$($VHDInfo.PhysicalSectorSize)"
		Write-LogDbg "  BlockSize            :$($VHDInfo.BlockSize)"
		Write-LogDbg "Validation successful."
	} catch {
		Write-LogErr "Failed: Get-VHD -Path $vhdPath"
		Throw "INVALID_VHD_EXCEPTION"
	}
}

Function Validate-XmlFiles( [string]$ParentFolder ) {
	Write-LogInfo "Validating XML Files from $ParentFolder folder recursively..."
	$allXmls = Get-ChildItem "$ParentFolder\*.xml" -Recurse
	$xmlErrorFiles = @()
	foreach ($file in $allXmls) {
		try {
			$null = [xml](Get-Content $file.FullName)
		} catch {
			Write-LogErr -text "$($file.FullName) validation failed."
			$xmlErrorFiles += $file.FullName
		}
	}
	if ( $xmlErrorFiles.Count -gt 0 ) {
		$xmlErrorFiles | ForEach-Object -Process {Write-LogInfo $_}
		Throw "Please fix above ($($xmlErrorFiles.Count)) XML files."
	}
}

Function Get-Cred($user, $password) {
	$secstr = New-Object -TypeName System.Security.SecureString
	$password.ToCharArray() | ForEach-Object {$secstr.AppendChar($_)}
	$cred = New-Object -typename System.Management.Automation.PSCredential -argumentlist $user, $secstr
	Set-Item WSMan:\localhost\Client\TrustedHosts * -Force
	return $cred
}

Function Wait-Time($seconds,$minutes,$hours) {
	if (!$hours -and !$minutes -and !$seconds) {
		Write-Output "At least hour, minute or second requires"
	} else {
		if (!$hours) {
			$hours = 0
		}
		if (!$minutes) {
			$minutes = 0
		}
		if (!$seconds) {
			$seconds = 0
		}

		$timeToSleepInSeconds = ($hours*60*60) + ($minutes*60) + $seconds
		$secondsRemaining = $timeToSleepInSeconds
		$secondsRemainingPercentage = (100 - (($secondsRemaining/$timeToSleepInSeconds)*100))
		for ($i = 1; $i -le $timeToSleepInSeconds; $i++) {
			write-progress -Id 27 -activity SLEEPING -Status "$($secondsRemaining) seconds remaining..." -percentcomplete $secondsRemainingPercentage
			$secondsRemaining = $timeToSleepInSeconds - $i
			$secondsRemainingPercentage = (100 - (($secondsRemaining/$timeToSleepInSeconds)*100))
			Start-Sleep -Seconds 1
		}
		write-progress -Id 27 -activity SLEEPING -Status "Wait Completed..!" -Completed
	}
}

function Get-UnixVMTime {
	param (
		[String] $Ipv4,
		[String] $Port,
		[String] $Username,
		[String] $Password
	)

	$unixTimeStr = $null

	$unixTimeStr = Get-TimeFromVM -Ipv4 $Ipv4 -Port $Port `
		-Username $Username -Password $Password
	if (-not $unixTimeStr -and $unixTimeStr.Length -lt 10) {
		return $null
	}

	return $unixTimeStr
}

function Convert-StringToUInt64 {
	param (
		[string] $str
	)

	$uint64Size = $null
	#
	# Make sure we received a string to convert
	#
	if (-not $str) {
		Write-LogErr "ConvertStringToUInt64() - input string is null"
		return $null
	}

	if ($str.EndsWith("MB")) {
		$num = $str.Replace("MB","")
		$uint64Size = ([Convert]::ToUInt64($num)) * 1MB
	} elseif ($str.EndsWith("GB")) {
		$num = $str.Replace("GB","")
		$uint64Size = ([Convert]::ToUInt64($num)) * 1GB
	} elseif ($str.EndsWith("TB")) {
		$num = $str.Replace("TB","")
		$uint64Size = ([Convert]::ToUInt64($num)) * 1TB
	} else {
		Write-LogErr "Invalid newSize parameter: ${str}"
		return $null
	}

	return $uint64Size
}

function Convert-StringToDecimal {
	Param (
		[string] $Str
	)
	$uint64Size = $null

	# Make sure we received a string to convert
	if (-not $Str) {
		Write-LogErr "Convert-StringToDecimal() - input string is null"
		return $null
	}

	if ($Str.EndsWith("MB")) {
		$num = $Str.Replace("MB","")
		$uint64Size = ([Convert]::ToDecimal($num)) * 1MB
	} elseif ($Str.EndsWith("GB")) {
		$num = $Str.Replace("GB","")
		$uint64Size = ([Convert]::ToDecimal($num)) * 1GB
	} elseif ($Str.EndsWith("TB")) {
		$num = $Str.Replace("TB","")
		$uint64Size = ([Convert]::ToDecimal($num)) * 1TB
	} else {
		Write-LogErr "Invalid newSize parameter: ${Str}"
		return $null
	}

	return $uint64Size
}

function Generate-RandomString {
	param(
		[Int] $length
	)

	$set = "abcdefghijklmnopqrstuvwxyz0123456789".ToCharArray()
	$result = ""
	for ($x = 0; $x -lt $length; $x++) {
		$result += $set | Get-Random
	}
	return $result
}

# Checks if MAC is valid. Delimiter can be : - or nothing
function Is-ValidMAC {
	param (
		[String]$macAddr
	)

	$retVal = $macAddr -match '^([0-9a-fA-F]{2}[:-]{0,1}){5}[0-9a-fA-F]{2}$'
	return $retVal
}

# This function removes all the invalid characters from given filename.
# Do not pass file paths (relative or full) to this function.
# Only file name is supported.
Function Remove-InvalidCharactersFromFileName {
	param (
		[String]$FileName
	)
	$WindowsInvalidCharacters = [IO.Path]::GetInvalidFileNameChars() -join ''
	$Regex = "[{0}]" -f [RegEx]::Escape($WindowsInvalidCharacters)
	return ($FileName -replace $Regex)
}

Function Extract-ZipFile {
	param ([string] $FileName, [string] $TargetFolder)
	Add-Type -AssemblyName System.IO.Compression.FileSystem -PassThru
	[IO.Compression.ZipFile]::ExtractToDirectory($FileName, $TargetFolder)
}

Function Get-AndTestHostPublicIp {
	param ([string] $ComputerName)
	Write-LogInfo "Getting the public IP of server $ComputerName"
	$externalVSwitches = Get-VMSwitch -SwitchType External -ComputerName $ComputerName
	if ($externalVSwitches) {
		foreach ($vSwitch in $externalVSwitches) {
			$interfaceName = "vEthernet ($($vSwitch.Name))"
			$ipAddress = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -CimSession $ComputerName | `
				Where-Object InterfaceAlias -eq $interfaceName
			if ($ipAddress) {
				try {
					Test-Connection -ComputerName $ipAddress.IPAddress | Out-Null
					return $ipAddress.IPAddress
				} catch {
					Write-LogWarn "Fail to connect to IP $($ipAddress.IPAddress) of host $ComputerName"
				}
			}
		}
	} else {
		$ipAddresses = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -CimSession $ComputerName | `
			Where-Object InterfaceAlias -NotMatch "vEthernet" | Where-Object IPAddress -ne "127.0.0.1"
		foreach ($ipAddress in $ipAddresses) {
			try {
				Test-Connection -ComputerName $ipAddress.IPAddress | Out-Null
				return $ipAddress.IPAddress
			} catch {
				Write-LogWarn "Fail to connect to IP $($ipAddress.IPAddress) of host $ComputerName"
			}
		}
	}
	return $null
}

function Get-TestStatus {
	param($testStatus)
	if ($testStatus -imatch "TestFailed") {
		Write-LogErr "Test failed. Last known status: $currentStatus."
		$testResult = "FAIL"
	} elseif ($testStatus -imatch "TestAborted") {
		Write-LogErr "Test Aborted. Last known status : $currentStatus."
		$testResult = "ABORTED"
	} elseif ($testStatus -imatch "TestSkipped") {
		Write-LogErr "Test SKIPPED. Last known status : $currentStatus."
		$testResult = "SKIPPED"
	} elseif ($testStatus -imatch "TestCompleted") {
		Write-LogInfo "Test Completed."
		Write-LogInfo "Build is Success"
		$testResult = "PASS"
	} else {
		Write-LogErr "Test execution is not successful, check test logs in VM."
		$testResult = "ABORTED"
	}

	return $testResult
}