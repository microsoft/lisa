##############################################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# VmOfToday.ps1
<#
.SYNOPSIS
	This script can lock and release the latest resource group of specified pattern and tag in Azure

.PARAMETER
	-Operation, Release or GetAndLock
	-UserName, the user that want to get and lock or release the resource group
	-AzureSecretsFile, the path of Azure secrets file
	-RgPattern, the pattern of resource group name
	-TagName, the tag name to filter resource group, TagName and TagValue are optional
	-TagValue, the tag value to filter resource group

.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE
	To get and lock the latest RG which matches "ICA*" and has tag "VmOfToday=yes" for user somebody@microsoft.com
	VmOfToday.ps1 -Operation GetAndLock -UserName "somebody@microsoft.com" -AzureSecretsFile $pathToSecret `
		-RgPattern "ICA*" -TagName "VmOfToday" -TagValue "yes"

	To release the RGs locked by user somebody@microsft, which matches "ICA*" and has tag "VmOfToday=yes"
	VmOfToday.ps1 -Operation Release -UserName "somebody@microsoft.com" -AzureSecretsFile $pathToSecret `
		-RgPattern "ICA*" -TagName "VmOfToday" -TagValue "yes"

#>
###############################################################################################

param
(
	[ValidateSet('Lock','Unlock', IgnoreCase = $false)]
	[string]$Operation,
	[string]$UserName,
	[string]$AzureSecretsFile,
	[string]$RgPattern,
	[string]$TagName,
	[string]$TagValue
)

Function Initialize-Environment($AzureSecretsFile, $LogFileName) {
	Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }
	if (!$global:LogFileName){
		Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force
	}

	#Read secrets file and terminate if not present.
	if ($AzureSecretsFile)
	{
		$secretsFile = $AzureSecretsFile
	}
	elseif ($env:Azure_Secrets_File)
	{
		$secretsFile = $env:Azure_Secrets_File
	}
	else
	{
		Write-LogInfo "-AzureSecretsFile and env:Azure_Secrets_File are empty. Exiting."
		exit 1
	}
	if ( -not (Test-Path $secretsFile))
	{
		Write-LogInfo "Secrets file not found. Exiting."
		exit 1
	}
	Write-LogInfo "Secrets file found."
	.\Utilities\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $secretsFile
}

Function Add-ResultSummary($VmData, $Secrets, $Rg, $UsersToNotify) {
	$result = [ordered]@{}
	$result.Add("Creation Time", $Rg.Tags.CreationTime)
	$result.Add("Resource Group Name", $Rg.ResourceGroupName)
	$result.Add("Role Name", $VmData.roleName)
	$result.Add("Public IP Address", $VmData.PublicIP)
	$result.Add("SSH Port", $VmData.SSHPort)
	$result.Add("User Name", $Secrets.linuxTestUsername)
	$result.Add("Password", $Secrets.linuxTestPassword)
	$result.Add("Instance Size", $VmData.InstanceSize)
	$result.Add("Location", $VmData.Location)
	$result.Add("Locked By", $($UsersToNotify -join ','))
	$link = "https://ms.portal.azure.com/#resource/subscriptions/$($Secrets.SubscriptionID)/resourceGroups/$($Rg.ResourceGroupName)/overview"
	$result.Add("Resource Group Link", $link)
	$header = "[Latest Running VM Info]"
	$textSummary = "`r`n`r`n`r`n$header"
	$htmlSummary = "<html><body><span>$header</span><table>"
	foreach ($key in $result.Keys)
	{
		$textSummary += "`r`n{0,-25} {1,2} {2,-1}" -f $key, ":", $result[$key]
		$htmlSummary += "<tr><td>$key</td><td>:</td><td>$($result[$key])</td></tr>"
	}
	$textSummary += "`r`n`r`n"
	$htmlSummary += "</table></body></html>"

	Write-Output $textSummary
	$htmlSummary | Out-File vm_result.html -Encoding ASCII
}

Function Get-FilteredResourceGroups($RgPattern, $TagName, $TagValue) {
	$rgs = @()
	try {
		if ($TagName -and $TagValue) {
			Write-LogInfo "Try to get the resource groups of pattern $RgPattern, with tag $TagName = $TagValue"
			$rgs = Get-AzResourceGroup -Tag @{ $TagName=$TagValue } | Where-Object ResourceGroupName -Like $RgPattern | Sort-Object {$_.Tags.CreationTime -as [DateTime] } -Descending
		} else {
			Write-LogInfo "Try to get the resource groups of pattern $RgPattern"
			$rgs = Get-AzResourceGroup | Where-Object ResourceGroupName -Like $RgPattern | Sort-Object {$_.Tags.CreationTime -as [DateTime] } -Descending
		}
	}
	catch {
		Write-LogErr "Exception in getting resource groups : $($_.Exception.Message)"
	}
	return $rgs
}

Function Lock-LatestResourceGroup($UserName, $AzureSecretsFile, $RgPattern, $TagName, $TagValue){
	Initialize-Environment -AzureSecretsFile $AzureSecretsFile -logFileName "Lock-LatestResourceGroup.log"
	$xmlSecrets = [xml](Get-Content $AzureSecretsFile)

	$rgs = Get-FilteredResourceGroups -RgPattern $RgPattern -TagName $TagName -TagValue $TagValue

	$vmFound = $false
	$timerUser = "Timer Lock"
	# $UserName is empty if the job is scheduled by timer
	if (!$UserName) {
		$UserName = $timerUser
	}
	$usersToNotify = @()
	foreach ($rg in $rgs) {
		try {
			Write-LogInfo "Start to validate the deployments in resource group $($rg.ResourceGroupName)"
			$vmData = Get-AllDeploymentData -ResourceGroups $rg.ResourceGroupName
			$isVmAlive = Is-VmAlive -AllVMDataObject $vmData
			if ($isVmAlive -eq "False") {
				Write-LogErr "Failed to connect to $($vmData.RoleName), trying to find previous VM"
			} else {
				if ($UserName -ne $timerUser) {
					$usersToNotify += $UserName
				}
				$locks = Get-AzResourceLock -ResourceGroupName $rg.ResourceGroupName
				$shouldAddLock = $true
				foreach ($lock in $locks) {
					# Lock already exists
					if ($lock.Name -eq $UserName) {
						Write-LogInfo "The resource group $($rg.ResourceGroupName) is already locked for $($lock.Name)"
						$shouldAddLock = $false
					}
					# RG has been locked by other user
					elseif ($lock.Name -ne $timerUser) {
						Write-LogWarn "The resource group $($rg.ResourceGroupName) is locked by $($lock.Name)"
						if ($UserName -ne $timerUser) {
							$usersToNotify += $lock.Name
						}
					}
				}
				if ($shouldAddLock) {
					Write-LogInfo "Adding lock to the resource group $($rg.ResourceGroupName) for $UserName"
					New-AzResourceLock -LockName $UserName -LockLevel CanNotDelete -ResourceGroupName $rg.ResourceGroupName -Force | Out-Null
					if ($?) {
						Write-LogInfo "Resource group is locked successfully"
					} else {
						Write-LogErr "Resource group is NOT locked successfully"
					}
				}

				Add-ResultSummary -VmData $vmData -Secrets $xmlSecrets.Secrets -Rg $rg -UsersToNotify $usersToNotify

				$vmFound = $true
				break
			}
		}
		catch {
			Write-LogErr "Exception occurred in Lock-LatestResourceGroup: $($_.Exception.Message)"
			Write-LogInfo "Trying to find previous running VM..."
		}
	}
	if (-not $vmFound) {
		Write-LogErr "Cannot find valid running VM."
	}
	if ($usersToNotify.Count -gt 0) {
		"USERS_TO_NOTIFY=$($usersToNotify -join ',')" | Out-File env.properties -Encoding ASCII
	}
}

Function Unlock-LockedResourceGroup($UserName, $AzureSecretsFile, $RgPattern, $TagName, $TagValue){
	Initialize-Environment -AzureSecretsFile $AzureSecretsFile -logFileName "Unlock-LockedResourceGroup.log"

	$rgs = Get-FilteredResourceGroups -RgPattern $RgPattern -TagName $TagName -TagValue $TagValue

	$isLatestLocked = $true
	$timerUser = "Timer Lock"
	# $UserName is empty if the job is scheduled by timer
	if (!$UserName) {
		$UserName = $timerUser
	}
	$usersToNotify = @()
	$rgLockedLong = @()
	foreach ($rg in $rgs)
	{
		try {
			Write-LogInfo "Getting the lock on resource group $($rg.ResourceGroupName)"
			$locks = Get-AzResourceLock -ResourceGroupName $rg.ResourceGroupName
			foreach ($lock in $locks) {
				# Lock added by timer on old RGs should be removed
				if (-not $isLatestLocked -and $lock.Name -eq $timerUser) {
					Write-LogInfo "Removing the Timer RG lock on old RG $($rg.ResourceGroupName)..."
					Remove-AzResourceLock -LockName $lock.Name -ResourceGroupName $rg.ResourceGroupName -Force
				}
				# Lock added by the user should be released
				elseif ($lock.Name -eq $UserName -and $UserName -ne $timerUser) {
					Write-LogInfo "Removing the RG lock for $UserName on RG $($rg.ResourceGroupName)..."
					Remove-AzResourceLock -LockName $lock.Name -ResourceGroupName $rg.ResourceGroupName -Force
				}
				# RG locked for over 15 days, need to notify the users who locked it
				elseif ($lock.Name.Contains('@') -and [DateTime]::Parse($rg.Tags.CreationTime) -le [DateTime]::Now.AddDays(-15))
				{
					$usersToNotify += $lock.Name
					$rgLockedLong += $rg.ResourceGroupName
				}
			}
			if ($locks)
			{
				$isLatestLocked = $false
			}
		}
		catch {
			Write-LogErr "Exception occurred in Unlock-LockedResourceGroup : $($_.Exception.Message)"
		}
	}
	if ($usersToNotify.Count -gt 0 -and $rgLockedLong.Count -gt 0) {
		"USERS_TO_NOTIFY=$($usersToNotify -join ',')" | Out-File env.properties -Encoding ASCII
		"RG_NAME=$($rgLockedLong -join '<br/>')" | Out-File env.properties -Append -Encoding ASCII
	}
}

if ($Operation -eq "Unlock") {
	Unlock-LockedResourceGroup -UserName $UserName -AzureSecretsFile $AzureSecretsFile -RgPattern $RgPattern -TagName $TagName -TagValue $TagValue
}
elseif ($Operation -eq "Lock") {
	Lock-LatestResourceGroup -UserName $UserName -AzureSecretsFile $AzureSecretsFile -RgPattern $RgPattern -TagName $TagName -TagValue $TagValue
}