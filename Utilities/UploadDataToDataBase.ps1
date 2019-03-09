##############################################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# UploadDataToDataBase.ps1
<#
.SYNOPSIS
	This script can upload data into database.

.PARAMETER
	-SQLQuery, SQL Scripts
	-AzureSecretsFile, the path of Azure secrets file

.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE
	UploadDataToDataBase.ps1 -SQLQuery "update Table set columna='a' where columnb='b'" -XMLSecretFile $pathToSecret

#>
###############################################################################################
Param
(
	[string]$SQLQuery,
	[string]$AzureSecretsFile
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

try
{
	$ExitCode = 1
	$XmlSecrets = ""
	if (![String]::IsNullOrEmpty($AzureSecretsFile) -and (Test-Path -Path $AzureSecretsFile) -eq $true) {
		$XmlSecrets = ([xml](Get-Content $AzureSecretsFile))
	} else {
		Write-Host "Error: Please provide value for -AzureSecretsFile"
	}
	if (![String]::IsNullOrEmpty($XmlSecrets)) {
		$dataSource = $XmlSecrets.secrets.DatabaseServer
		$dbuser = $XmlSecrets.secrets.DatabaseUser
		$dbpassword = $XmlSecrets.secrets.DatabasePassword
		$database = $XmlSecrets.secrets.DatabaseName

		if ($dataSource -and $dbuser -and $dbpassword -and $database) {
			try {
				Write-Host "Info: SQLQuery:  $SQLQuery"
				$connectionString = "Server=$dataSource;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
				$connection = New-Object System.Data.SqlClient.SqlConnection
				$connection.ConnectionString = $connectionString
				$connection.Open()
				$command = $connection.CreateCommand()
				$command.CommandText = $SQLQuery
				$null = $command.executenonquery()
				$connection.Close()
				$ExitCode = 0
				Write-Host "Info: Uploading data to database :  done!!!"
			} catch {
				Write-Host "Error: Uploading data to database :  ERROR"
				$line = $_.InvocationInfo.ScriptLineNumber
				$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
				$ErrorMessage =  $_.Exception.Message
				Write-Host "Error: EXCEPTION : $ErrorMessage"
				Write-Host "Error: Source : Line $line in script $script_name."
			}
		} else {
			Write-Host "Error: Database details are not provided. Data will not be uploaded to database!!!"
		}
	} else {
		Write-Host "Error: Unable to send data to database. XML Secrets file not provided."
	}
} catch {
	Raise-Exception($_)
} finally {
	Write-Host "Info: Exiting with code : $ExitCode"
	exit $ExitCode
}


