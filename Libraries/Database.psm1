##############################################################################################
# Database.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation.
	Functions that handles database operation

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Function Get-SQLQueryOfTelemetryData ($TestPlatform,$TestLocation,$TestCategory,$TestArea,$TestName,$CurrentTestResult, `
									$ExecutionTag,$GuestDistro,$KernelVersion,$LISVersion,$HostVersion,$VMSize, `
									$Networking,$ARMImageName,$OsVHD,$LogFile,$BuildURL)
{
	try
	{
		$TestResult = $CurrentTestResult.TestResult
		$TestSummary = $CurrentTestResult.TestSummary
		$UTCTime = (Get-Date).ToUniversalTime()
		$DateTimeUTC = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day) $($UTCTime.Hour):$($UTCTime.Minute):$($UTCTime.Second)"
		$testLogStorageAccount = $XmlSecrets.secrets.testLogsStorageAccount
		$testLogStorageAccountKey = $XmlSecrets.secrets.testLogsStorageAccountKey
		$testLogFolder = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day)"
		$ticks= (Get-Date).Ticks
		$uploadFileName = Join-Path $env:TEMP "$TestName-$ticks.zip"
		$null = New-ZipFile -zipFileName $uploadFileName -sourceDir $LogDir
		$UploadedURL = .\Utilities\UploadFilesToStorageAccount.ps1 -filePaths $uploadFileName `
		-destinationStorageAccount $testLogStorageAccount -destinationContainer "lisav2logs" `
		-destinationFolder "$testLogFolder" -destinationStorageKey $testLogStorageAccountKey
		if ($BuildURL) {
			$BuildURL = "$BuildURL`consoleFull"
		} else {
			$BuildURL = ""
		}
		$dataTableName = "LISAv2Results"
		$SQLQuery = "INSERT INTO $dataTableName (DateTimeUTC,TestPlatform,TestLocation,TestCategory,TestArea,TestName,TestResult,SubTestName,SubTestResult,ExecutionTag,GuestDistro,KernelVersion,LISVersion,HostVersion,VMSize,Networking,ARMImage,OsVHD,LogFile,BuildURL) VALUES "
		$SQLQuery += "('$DateTimeUTC','$TestPlatform','$TestLocation','$TestCategory','$TestArea','$TestName','$testResult','','','$ExecutionTag','$GuestDistro','$KernelVersion','$LISVersion','$HostVersion','$VMSize','$Networking','$ARMImageName','$OsVHD','$UploadedURL', '$BuildURL'),"
		if ($TestSummary) {
			foreach ($tempResult in $TestSummary.Split('>')) {
				if ($tempResult) {
					$tempResult = $tempResult.Trim().Replace("<br /","").Trim()
					$subTestResult = $tempResult.Split(":")[$tempResult.Split(":").Count -1 ].Trim()
					$subTestName = $tempResult.Replace("$subTestResult","").Trim().TrimEnd(":").Trim()
					$SQLQuery += "('$DateTimeUTC','$TestPlatform','$TestLocation','$TestCategory','$TestArea','$TestName','$testResult','$subTestName','$subTestResult','$ExecutionTag','$GuestDistro','$KernelVersion','$LISVersion','$HostVersion','$VMSize','$Networking','$ARMImageName','$OsVHD','$UploadedURL', '$BuildURL'),"
				}
			}
		}
		$SQLQuery = $SQLQuery.TrimEnd(',')
		Write-LogInfo "Get the SQL query of test results:  done"
		return $SQLQuery
	}
	catch
	{
		Write-LogErr "Get the SQL query of test results:  ERROR"
		$line = $_.InvocationInfo.ScriptLineNumber
		$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
		$ErrorMessage =  $_.Exception.Message
		Write-LogInfo "EXCEPTION : $ErrorMessage"
		Write-LogInfo "Source : Line $line in script $script_name."
	}
}

Function Upload-TestResultToDatabase ($SQLQuery)
{
	if ($XmlSecrets) {
		$dataSource = $XmlSecrets.secrets.DatabaseServer
		$dbuser = $XmlSecrets.secrets.DatabaseUser
		$dbpassword = $XmlSecrets.secrets.DatabasePassword
		$database = $XmlSecrets.secrets.DatabaseName

		if ($dataSource -and $dbuser -and $dbpassword -and $database) {
			try
			{
				Write-LogInfo "SQLQuery:  $SQLQuery"
				$connectionString = "Server=$dataSource;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
				$connection = New-Object System.Data.SqlClient.SqlConnection
				$connection.ConnectionString = $connectionString
				$connection.Open()
				$command = $connection.CreateCommand()
				$command.CommandText = $SQLQuery
				$null = $command.executenonquery()
				$connection.Close()
				Write-LogInfo "Uploading test results to database :  done!!"
			}
			catch
			{
				Write-LogErr "Uploading test results to database :  ERROR"
				$line = $_.InvocationInfo.ScriptLineNumber
				$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
				$ErrorMessage =  $_.Exception.Message
				Write-LogInfo "EXCEPTION : $ErrorMessage"
				Write-LogInfo "Source : Line $line in script $script_name."
			}
		} else {
			Write-LogErr "Database details are not provided. Results will not be uploaded to database!!"
		}
	} else {
		Write-LogErr "Unable to send telemetry data to Azure. XML Secrets file not provided."
	}
}