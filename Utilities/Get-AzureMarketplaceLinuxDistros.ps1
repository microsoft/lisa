# Copyright (c) Microsoft Corporation

# Description: This script collect all distro images from all Azure regions

param
(
	[String] $AzureSecretsFile,
	[String] $Location = "westus2",
	[String] $Publisher = "Canonical,OpenLogic,RedHat,SUSE,credativ,CoreOS,Debian",
	[string] $LogFileName = "GetAllLinuxDistros.log",
	[string] $TableName = "AzureMarketplaceDistroInfo",
	[int] $CheckInternalInDays = 1,
	[string] $ResultFolder = "DistroResults"
)

function Update-DeletedImages($Date, $Location) {
	$server = $XmlSecrets.secrets.DatabaseServer
	$dbuser = $XmlSecrets.secrets.DatabaseUser
	$dbpassword = $XmlSecrets.secrets.DatabasePassword
	$database = $XmlSecrets.secrets.DatabaseName
	
	# Query if the image exists in the database
	$sqlQuery = "SELECT ID from $TableName where LastCheckedDate <= '$($Date.AddDays(-$CheckInternalInDays))' and IsAvailable = 1 and Location='$Location'"

	$connectionString = "Server=$server;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
	$connection = New-Object System.Data.SqlClient.SqlConnection
	$connection.ConnectionString = $connectionString
	$connection.Open()
	$command = $connection.CreateCommand()
	$command.CommandText = $SQLQuery
	$reader = $command.ExecuteReader()
	# For every available image not updated, mark it as deleted
	$sqlQuery = ""
	while ($reader.Read()) {
		$id = $reader.GetValue($reader.GetOrdinal("ID"))
		$sqlQuery += "Update $tableName Set LastCheckedDate='$date', IsAvailable=0, DeletedOn='$date' where ID=$id;"
	}
	if ($sqlQuery) {
		Upload-TestResultToDatabase -SQLQuery $sqlQuery.Trim(";")
	}
}

function Update-DatabaseRecord($Publisher, $Offer, $Sku, $Version, $Date, $Location) {
	$server = $XmlSecrets.secrets.DatabaseServer
	$dbuser = $XmlSecrets.secrets.DatabaseUser
	$dbpassword = $XmlSecrets.secrets.DatabasePassword
	$database = $XmlSecrets.secrets.DatabaseName
	
	# Query if the image exists in the database
	$sqlQuery = "SELECT ID from $TableName where Location='$Location' and FullName= '$Publisher $Offer $Sku $Version'"

	$connectionString = "Server=$server;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
	$connection = New-Object System.Data.SqlClient.SqlConnection
	$connection.ConnectionString = $connectionString
	$connection.Open()
	$command = $connection.CreateCommand()
	$command.CommandText = $SQLQuery
	$reader = $command.ExecuteReader()
	# If the record exists, update the LastCheckedDate
	if ($reader.Read()) {
		$id = $reader.GetValue($reader.GetOrdinal("ID"))
		$sqlQuery = "Update $tableName Set LastCheckedDate='$date', IsAvailable=1 where ID=$id"
	# If the record doesn't exist, insert a new record
	} else {
		$distroName = "$Publisher $Offer $Sku $Version"
		$sqlQuery = "INSERT INTO $tableName (LastCheckedDate, Location, Publisher, Offer, SKU, Version, FullName, AvailableOn, IsAvailable) VALUES
			('$Date', '$Location', '$Publisher', '$Offer', '$Sku', '$Version', '$distroName', '$Date', 1)"
	}
	Upload-TestResultToDatabase -SQLQuery $sqlQuery
}

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
$PublisherArrayInScope = $Publisher.Trim(", ").Split(",").Trim()

# this should be {westus2 -> {Publisher -> {Offer -> {SKU -> {Version -> "Gallery ARM Image Name"}}}}}
$RegionDistros = @{}
# this should be {"Gallery ARM Image Name" -> ("westus2","eastus2")}
$DistroRegions = @{}

$date = (Get-Date).ToUniversalTime()
$sqlQuery = ""
$count = 0
$allRegions = Get-AzLocation | select -ExpandProperty Location | where {!$RegionArrayInScope -or ($RegionArrayInScope -contains $_)}
foreach ($locName in $allRegions) {
	Write-Host "processing $locName"
	if (!$RegionDistros.$locName) {
		$RegionDistros["$locName"] = @{}
	}
	$allRegionPublishers = Get-AzVMImagePublisher -Location $locName | Select -ExpandProperty PublisherName | where {(!$PublisherArrayInScope -or ($PublisherArrayInScope -contains $_))}
	foreach ($pubName in $allRegionPublishers) {
		Write-Host "processing $locName $pubName"
		if (!$RegionDistros.$locName.$pubName) {
			$RegionDistros["$locName"]["$pubName"] = @{}
		}
		$allRegionPublisherOffers = Get-AzVMImageOffer -Location $locName -PublisherName $pubName | Select -ExpandProperty Offer
		foreach ($offerName in $allRegionPublisherOffers) {
			Write-Host "processing $locName $pubName $offerName"
			if (!$RegionDistros.$locName.$pubName.$offerName) {
				$RegionDistros["$locName"]["$pubName"]["$offerName"] = @{}
			}
			$allRegionPublisherOfferSkus = Get-AzVMImageSku -Location $locName -PublisherName $pubName -Offer $offerName | Select -ExpandProperty Skus
			foreach ($skuName in $allRegionPublisherOfferSkus) {
				Write-Host "processing $locName $pubName $offerName $skuName"
				if (!$RegionDistros.$locName.$pubName.$skuName) {
					$RegionDistros["$locName"]["$pubName"]["$skuName"] = @{}
				}
				$allRegionPublisherVersions = Get-AzVMImage -Location $locName -PublisherName $pubName -Offer $offerName -Sku $skuName | Select -ExpandProperty Version
				foreach ($skuVersion in $allRegionPublisherVersions) {
					Write-Host "processing $locName $pubName $offerName $skuName $skuVersion"
					$image = Get-AzVMImage -Location $locName -PublisherName $pubName -Offer $offerName -Sku $skuName -Version $skuVersion
					$distroName = "$pubName $offerName $skuName $skuVersion"
					if (!$RegionDistros.$locName.$pubName.$skuName.$skuVersion) {
						$RegionDistros["$locName"]["$pubName"]["$skuName"]["$skuVersion"] = $distroName
					}
					if ($image.OSDiskImage.OperatingSystem -eq "Linux") {
						Update-DatabaseRecord -Publisher $pubName -Offer $offerName -Sku $skuName -Version $skuVersion -Date $date -Location $locName

						if (!$DistroRegions.$distroName) {
							$DistroRegions["$distroName"] = [System.Collections.ArrayList]@()
						}
						if ($DistroRegions.$distroName -notcontains $locName) {
							$null = $DistroRegions.$distroName.Add($locName)
						}
					}
				}
			}
		}
	}
	Update-DeletedImages -Date $date -Location $locName
}

if (!(Test-Path $ResultFolder))
{
	New-Item -Path $ResultFolder -ItemType Directory -Force | Out-Null
}

$count = $DistroRegions.Keys.Count
$PublisherArrayInScope | % {
	$pubName = $_
	$DistroRegions.GetEnumerator() | where-object {$_.Name -imatch "^$pubName"} | sort Name | Select-Object @{l="DistroName";e={$_.Name.Trim()}}   | out-file -FilePath "$ResultFolder/${pubName}_Distros.txt"
}
$Path = "$ResultFolder/AllLinuxDistros_" + (Get-Date).ToString("yyyyMMdd_hhmmss") + ".csv" 
$DistroRegions.GetEnumerator() | sort Name | Select-Object Name, @{l = "Location"; e = { $_.Value } } | Export-Csv -Path $Path -NoTypeInformation -Force
Write-Host "Total Distro collected: $count"