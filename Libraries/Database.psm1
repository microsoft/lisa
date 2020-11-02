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

Function Get-SQLQueryOfTelemetryData ($TestPlatform, $TestLocation, $TestCategory, $TestArea, $TestName, $CurrentTestResult, `
		$ExecutionTag, $GuestDistro, $KernelVersion, $HardwarePlatform, $LISVersion, $HostVersion, $VMSize, $VMGeneration, `
		$Networking, $ARMImageName, $OsVHD, $LogFile, $BuildURL, $TableName, $TestPassID, $FailureReason) {
	try {
		$TestResult = $CurrentTestResult.TestResult
		$TestSummary = $CurrentTestResult.TestSummary
		$UTCTime = (Get-Date).ToUniversalTime()
		$DateTimeUTC = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day) $($UTCTime.Hour):$($UTCTime.Minute):$($UTCTime.Second)"
		$testLogStorageAccount = $XmlSecrets.secrets.testLogsStorageAccount
		$testLogStorageAccountKey = $XmlSecrets.secrets.testLogsStorageAccountKey
		$testLogFolder = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day)"
		$ticks = (Get-Date).Ticks
		$uploadFileName = Join-Path $env:TEMP "$TestName-$ticks.zip"
		$null = New-ZipFile -zipFileName $uploadFileName -sourceDir $LogDir
		$UploadedURL = .\Utilities\UploadFilesToStorageAccount.ps1 -filePaths $uploadFileName `
			-destinationStorageAccount $testLogStorageAccount -destinationContainer "lisav2logs" `
			-destinationFolder "$testLogFolder" -destinationStorageKey $testLogStorageAccountKey
		if ($BuildURL) {
			$BuildURL = "$BuildURL`consoleFull"
		}
		else {
			$BuildURL = ""
		}
		$SQLQuery = "INSERT INTO $TableName (DateTimeUTC,TestPlatform,TestLocation,TestCategory,TestArea,TestName,TestResult,ExecutionTag,GuestDistro,KernelVersion,HardwarePlatform,LISVersion,HostVersion,VMSize,VMGeneration,ARMImage,OsVHD,LogFile,BuildURL,TestPassID,FailureReason,TestResultDetails) VALUES "
		$SQLQuery += "('$DateTimeUTC','$TestPlatform','$TestLocation','$TestCategory','$TestArea','$TestName','$testResult','$ExecutionTag','$GuestDistro','$KernelVersion','$HardwarePlatform','$LISVersion','$HostVersion','$VMSize','$VMGeneration','$ARMImageName','$OsVHD','$UploadedURL','$BuildURL','$TestPassID','$FailureReason',"
		$TestResultDetailsValue = ""
		if ($TestSummary) {
			foreach ($tempResult in $TestSummary.Split('>')) {
				if ($tempResult) {
					$TestResultDetailsValue += $tempResult.Trim().Replace("<br /", "; `r`n").Replace("'", """") -replace "{|}", " "
				}
			}
		}
		if ($Networking) {
			$TestResultDetailsValue += "Networking: $Networking; `r`n"
		}
		$SQLQuery += "'$TestResultDetailsValue')"
		Write-LogInfo "Get the SQL query of test results:  done"
		return $SQLQuery
	}
	catch {
		Write-LogErr "Get the SQL query of test results:  ERROR"
		$line = $_.InvocationInfo.ScriptLineNumber
		$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
		$ErrorMessage = $_.Exception.Message
		Write-LogInfo "EXCEPTION : $ErrorMessage"
		Write-LogInfo "Source : Line $line in script $scriptName."
	}
}

Function Invoke-IngestKustoFromTSQL([string]$SQLString) {
	try {
		$kustoClusterURI = $global:XmlSecrets.secrets.KustoClusterURI
		$kustoDatabase = $global:XmlSecrets.secrets.KustoDatabase
		$kustoDataDLLPath = $global:XmlSecrets.secrets.KustoDataDLLPath
		if ($kustoClusterURI -and $kustoDatabase -and $kustoDataDLLPath) {
			# Replace potential [''] in field value string
			$SQLString = $SQLString -replace "(?<![,\(])\'\'(?![,\)])" , '"'
			$insertTSQLPattern = "(?in:^\s*INSERT\s+INTO\s+(?<tablename>\w+)\s*\(\s*(?<columns>(\w+\s*,\s*)+\w+)\s*\)\s*VALUES\s*(\(\s*(?<values>(\'[^\']*\',)*\s*\'[^\']*\')\s*\)\s*,*\s*)+$)"
			$allMatches = Select-String -Pattern $insertTSQLPattern -Input $SQLString -AllMatches
			if ($allMatches.Matches) {
				foreach ($matchGroup in $allMatches.Matches.Groups) {
					if ($matchGroup.Name -eq "tablename") {
						$tableName = $matchGroup.Value
					}
					elseif ($matchGroup.Name -eq "columns") {
						$columns = @($matchGroup.Value.Split(',').Trim())
					}
					elseif ($matchGroup.Name -eq "values") {
						$valueArr = @($matchGroup.Captures.Value | Where-Object { $_ -ne "" })
					}
				}
				if ($tableName -and $columns -and $valueArr) {
					$ingestInlineCmd = ".ingest inline into table $tableName "
					$kcsb = New-Object Kusto.Data.KustoConnectionStringBuilder ("$kustoClusterURI;Fed=True", $kustoDatabase)
					$azAccountType = $global:GlobalConfig.Global.Azure.Subscription.AccountType
					if ($azAccountType -eq "ServicePrincipal") {
						$applicationId = $global:XmlSecrets.secrets.SubscriptionServicePrincipalClientID
						$authority = $global:XmlSecrets.secrets.SubscriptionServicePrincipalTenantID
						$applicationKey = $global:XmlSecrets.secrets.SubscriptionServicePrincipalKey
						$kcsb = $kcsb.WithAadApplicationKeyAuthentication($applicationId, $applicationKey, $authority)
					}
					elseif ($azAccountType -eq "ManagedService") {
						$msiClientId = $global:XmlSecrets.secrets.MsiClientId
						$kcsb = $kcsb.WithAadManagedIdentity($msiClientId)
					}
					$queryProvider = [Kusto.Data.Net.Client.KustoClientFactory]::CreateCslQueryProvider($kcsb)
					# Query first to get table schema, and prepare ingest inline command
					$crp = New-Object Kusto.Data.Common.ClientRequestProperties
					$crp.ClientRequestId = "MyPowershellScript.ExecuteQuery." + [Guid]::NewGuid().ToString()
					$crp.SetOption([Kusto.Data.Common.ClientRequestProperties]::OptionServerTimeout, [TimeSpan]::FromSeconds(30))
					# Here may throw exception, when $tableName does not exist
					$queryReader = $queryProvider.ExecuteQuery("$tableName | limit 1", $crp)
					$queryDataTable = [Kusto.Cloud.Platform.Data.ExtendedDataReader]::ToDataSet($queryReader).Tables[0]
					$kustoTableColumns = @($queryDataTable.Columns.ColumnName)
					foreach ($rowValue in $valueArr) {
						$ingestValueArray = @($kustoTableColumns)
						$cellValueIndex = 0
						$cellValueArray = @(($rowValue | Select-String -Pattern "\'([^\']*)\'" -AllMatches).Matches | ForEach-Object { $_.Groups[1].Value })
						for ($tableColumnIndex = 0; $tableColumnIndex -lt $kustoTableColumns.Count; $tableColumnIndex++) {
							if ($columns -contains $kustoTableColumns[$tableColumnIndex]) {
								$ingestValueArray[$tableColumnIndex] = $cellValueArray[$cellValueIndex++].Replace(",", " ").Replace("""", "'")
							}
							else {
								$ingestValueArray[$tableColumnIndex] = ""
							}
						}
						$ingestInlineCmd += " [ $($ingestValueArray -Join ',') ]"
					}
					# Execute ingest command with AdminProvider
					$adminProvider = [Kusto.Data.Net.Client.KustoClientFactory]::CreateCslAdminProvider($kcsb)
					# Here may throw exception, when schema does not match
					$adminReader = $adminProvider.ExecuteControlCommand($ingestInlineCmd)
					if ($adminReader.HasRows -and $adminReader["ExtentId"] -ne [Guid]::Empty) {
						Write-LogInfo "Ingested successfully into '$kustoDatabase' of '$kustoClusterURI' with `n $ingestInlineCmd "
					}
				}
				else {
					Write-LogErr "Missing 'tablename' or 'columns' or 'values' from SQLString '$SQLString', hence skip Kusto ingestion"
				}
			}
			else {
				Write-LogErr "Failed to parse SQLString '$SQLString', hence skip Kusto ingestion"
			}
		}
	}
	catch {
		Write-LogErr "Ingest Kusto Data from TSQLString:  ERROR"
		$line = $_.InvocationInfo.ScriptLineNumber
		$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
		$ErrorMessage = $_.Exception.Message
		Write-LogInfo "EXCEPTION : $ErrorMessage `n when ingesting into '$kustoDatabase' by '$kustoClusterURI' with '$ingestInlineCmd'"
		Write-LogInfo "Source : Line $line in script $scriptName."
	}
	finally {
		if ($queryProvider) { $queryProvider.Dispose() }
		if ($adminProvider) { $adminProvider.Dispose() }
	}
}

Function Upload-TestResultToDatabase ([String]$SQLQuery) {
	if ($XmlSecrets) {
		$dataSource = $XmlSecrets.secrets.DatabaseServer
		$dbuser = $XmlSecrets.secrets.DatabaseUser
		$dbpassword = $XmlSecrets.secrets.DatabasePassword
		$database = $XmlSecrets.secrets.DatabaseName

		if ($dataSource -and $dbuser -and $dbpassword -and $database) {
			$retry = 0
			$maxRetry = 3
			while ($retry -lt $maxRetry) {
				$retry++
				$uploadSucceeded = $true
				try {
					Write-LogInfo "SQLQuery:  $SQLQuery"
					$connectionString = "Server=$dataSource;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
					$connection = New-Object System.Data.SqlClient.SqlConnection
					$connection.ConnectionString = $connectionString
					$connection.Open()
					$command = $connection.CreateCommand()
					$command.CommandText = $SQLQuery
					$null = $command.executenonquery()
					$connection.Close()
					Write-LogInfo "Uploading test results to database: DONE"
				}
				catch {
					$uploadSucceeded = $false
					Write-LogErr "Uploading test results to database: ERROR"
					$line = $_.InvocationInfo.ScriptLineNumber
					$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
					$ErrorMessage = $_.Exception.Message
					Write-LogErr "EXCEPTION : $ErrorMessage"
					Write-LogErr "Source : Line $line in script $scriptName."
					if ($retry -lt $maxRetry) {
						Start-Sleep -Seconds 1
						Write-LogWarn "Retring, attempt $retry"
					}
					else {
						# throw from catch, in order to be caught by caller module/function
						throw $_.Exception
					}
				}
				finally {
					$connection.Close()
				}
				if ($uploadSucceeded) {
					break
				}
			}
		}
		else {
			Write-LogErr "Database details are not provided. Results will not be uploaded to database!!"
		}
	}
	else {
		Write-LogErr "Unable to send telemetry data to Azure. XML Secrets file not provided."
	}
}

Function Upload-TestResultDataToDatabase ([Array] $TestResultData, [Object] $DatabaseConfig) {
	$server = $DatabaseConfig.server
	$dbUser = $DatabaseConfig.user
	$dbPassword = $DatabaseConfig.password
	$dbName = $DatabaseConfig.dbname
	$tableName = $DatabaseConfig.dbtable

	if ($server -and $dbUser -and $dbPassword -and $dbName -and $tableName) {
		try {
			$connectionString = "Server=$server;uid=$dbuser; pwd=$dbpassword;Database=$dbName;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
			$connection = New-Object System.Data.SqlClient.SqlConnection
			$connection.ConnectionString = $connectionString
			$connection.Open()
			foreach ($map in $TestResultData) {
				$queryKey = "INSERT INTO $tableName ("
				$queryValue = "VALUES ("
				foreach ($key in $map.Keys) {
					$queryKey += "$key,"
					if (($null -ne $map[$key]) -and ($map[$key].GetType().Name -eq "String")) {
						$queryValue += "'$($map[$key])',"
					}
					else {
						$queryValue += "$($map[$key]),"
					}
				}
				$query = $queryKey.TrimEnd(",") + ") " + $queryValue.TrimEnd(",") + ")"
				Write-LogInfo "SQLQuery:  $query"
				$command = $connection.CreateCommand()
				$command.CommandText = $query
				$null = $command.executenonquery()
			}
			$connection.Close()
			Write-LogInfo "Succeed to upload test results to database"
		}
		catch {
			Write-LogErr "Fail to upload test results to database"
			$line = $_.InvocationInfo.ScriptLineNumber
			$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
			$ErrorMessage = $_.Exception.Message
			Write-LogInfo "EXCEPTION : $ErrorMessage"
			Write-LogInfo "Source : Line $line in script $scriptName."
			# throw from catch, in order to be caught by caller module/function
			throw $_.Exception
		}
		finally {
			$connection.Close()
		}
	}
 else {
		Write-LogErr "Database details are not provided. Results will not be uploaded to database."
	}
}

Function Get-VMProperties ($PropertyFilePath) {
	if (Test-Path $PropertyFilePath) {
		$GuestDistro = Get-Content $PropertyFilePath | Select-String "OS type" | ForEach-Object { $_ -replace ",OS type,", "" }
		$HostOS = Get-Content $PropertyFilePath | Select-String "Host Version" | ForEach-Object { $_ -replace ",Host Version,", "" }
		$KernelVersion = Get-Content $PropertyFilePath | Select-String "Kernel version" | ForEach-Object { $_ -replace ",Kernel version,", "" }

		$objNode = New-Object -TypeName PSObject
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name GuestDistro -Value $GuestDistro -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name HostOS -Value $HostOS -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name KernelVersion -Value $KernelVersion -Force
		return $objNode
	}
 else {
		Write-LogErr "The property file doesn't exist: $PropertyFilePath"
		return $null
	}
}

Function Run-SQLCmd {
	param (
		[string] $DBServer,
		[string] $DBName,
		[string] $DBUsername,
		[string] $DBPassword,
		[string] $SQLQuery
	)
	try {
		Write-LogInfo "$SQLQuery"
		$connectionString = "Server=$DBServer;uid=$DBUsername; pwd=$DBPassword;Database=$DBName;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
		$connection = New-Object System.Data.SqlClient.SqlConnection
		$connection.ConnectionString = $connectionString
		$connection.Open()
		$command = $connection.CreateCommand()
		$command.CommandText = $SQLQuery
		$null = $command.executenonquery()
		$connection.Close()
		Write-LogInfo "Done."
	}
	catch {
		Write-LogErr "SQL Query failed to execute."
		$ErrorMessage = $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogErr "EXCEPTION in Run-SQLCmd() : $ErrorMessage at line: $ErrorLine"
		# throw from catch, in order to be caught by caller module/function
		throw $_.Exception
	}
	finally {
		$connection.Close()
	}
}
