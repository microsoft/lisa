# Copyright (c) Microsoft Corporation
# Description: This script collect all distro images from all Azure regions

param
(
	[String] $AzureSecretsFile,
	[String] $Location,
	[string] $TableName = "AzureVMSize",
	[string] $ResultFolder = "DistroResults"
)

function Update-DatabaseRecord($Location, $ResultArray) {
	$server = $XmlSecrets.secrets.DatabaseServer
	$dbuser = $XmlSecrets.secrets.DatabaseUser
	$dbpassword = $XmlSecrets.secrets.DatabasePassword
	$database = $XmlSecrets.secrets.DatabaseName
	
	$sqlQuery = "INSERT INTO $tableName (Location, Name, NumberOfCores, MemoryInMB, MaxDataDiskCount, OSDiskSizeInMB, ResourceDiskSizeInMB) VALUES "
	$maxRecordPerQuery = 10;
	$batchCount = 0
	$totalCount = 0
	foreach ($line in $ResultArray) {
		$result = $line.Split(" ").Trim()
		$sqlQuery += "('$Location', '$($result[0])', $($result[1]), $($result[2]), $($result[3]), $($result[4]), $($result[5])),"
		$batchCount++
		$totalCount++

		if ($totalCount -eq $ResultArray.Count) {
			Upload-TestResultToDatabase -SQLQuery $sqlQuery.Trim(",")
		} elseif ($batchCount -eq $maxRecordPerQuery) {
			Upload-TestResultToDatabase -SQLQuery $sqlQuery.Trim(",")
			$sqlQuery = "INSERT INTO $tableName (Location, Name, NumberOfCores, MemoryInMB, MaxDataDiskCount, OSDiskSizeInMB, ResourceDiskSizeInMB) VALUES "
			$batchCount = 0
		}
	}
}

$LogFileName = "GetAllVMSize-$($Location.Replace(',','-')).log"
#Load libraries
if (!$global:LogFileName) {
	Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force
}
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

#Read secrets file and terminate if not present.
if ($AzureSecretsFile) {
	$secretsFile = $AzureSecretsFile
}
elseif ($env:Azure_Secrets_File) {
	$secretsFile = $env:Azure_Secrets_File
}
else {
	 Write-Host "-AzureSecretsFile and env:Azure_Secrets_File are empty. Exiting."
	 exit 1
}

if (Test-Path $secretsFile) {
	Write-Host "Secrets file found."
	Add-AzureAccountFromSecretsFile -CustomSecretsFilePath $AzureSecretsFile
	$secrets = [xml](Get-Content -Path $secretsFile)
	Set-Variable -Name XmlSecrets -Value $secrets -Scope Global -Force
}
 else {
	 Write-Host "Secrets file not found. Exiting."
	 exit 1
}

$RegionArrayInScope = $Location.Trim(", ").Split(",").Trim()

$allRegions = Get-AzLocation | select -ExpandProperty Location | where {!$RegionArrayInScope -or ($RegionArrayInScope -contains $_)}
# EUAP regions are not returned by Get-AzLocation
if ($RegionArrayInScope -imatch "euap") {
	$allRegions += ($RegionArrayInScope -imatch "euap")
}
$resultArray = @()
foreach ($locName in $allRegions) {
	Write-Host "processing $locName"
	$outputFile = ".\vmsize-$locName.txt"

	Get-AzVMSize -Location $locName | Out-File $outputFile -Encoding ascii
	$output = Get-Content -Path $outputFile
	$sizeBegin = $false
	foreach ($line in $output) {
		if ($line -imatch "----") {
			$sizeBegin = $true
			continue
		}
		if ($sizeBegin) {
			$size = ($line -replace "\s+"," ").Trim()
			if ($size) {
				$resultArray += $size
			}
		}
	}
	Update-DatabaseRecord -Location $locName -ResultArray $resultArray
}