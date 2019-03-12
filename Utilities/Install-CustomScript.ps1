##############################################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# Install-CustomScript.ps1
<#
.SYNOPSIS

.PARAMETER
	-AzureSecretsFile, the path of Azure secrets file
	-VmName, the name of the VM to install the CustomScript extension, if no VmName is provided, it will be installed on all VMs
	-ResourceGroupName, the resource group name of the VMs to install the CustomScript extension, if no ResourceGroupName is provided, it will be installed on all VMs in the subscription
	-FileUris, comma separated Uris of the custom scripts
	-CommandToRun, the command to run on the VM
	-StorageAccountName, the name of the storage account that contains the custom scripts
	-StorageAccountKey, the key of the storage account that contains the custom scripts
	-OSType, the type of the OS, Linux or Windows, valid only if neither VmName nor ResourceGroupName is provided

.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE
	.\Utilities\Install-CustomScript.ps1 -AzureSecretsFile <PathToSecretFile> -VmName <VmName> -ResourceGroupName <RgName> `
		-FileUris "https://teststorageaccout.blob.core.windows.net/script/install.sh" -CommandToRun "bash install.sh" `
		-StorageAccountName <StorageAccoutName> -StorageAccountKey <StorageAccountKey> -OSType Linux
#>
###############################################################################################

param
(
	[Parameter(Mandatory=$true)]
	[String] $AzureSecretsFile,
	[String] $VmName = "",
	[String] $ResourceGroupName = "",
	[Parameter(Mandatory=$true)]
	[String] $FileUris,
	[Parameter(Mandatory=$true)]
	[String] $CommandToRun,
	[String] $StorageAccountName = "",
	[String] $StorageAccountKey = "",
	[ValidateSet('Linux','Windows', IgnoreCase = $false)]
	[String] $OSType = "Linux"
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

Function Install-CustomScript($AzureSecretsFile, $FileUris, $CommandToRun, $StorageAccountName, $StorageAccountKey, $VmName, $ResourceGroupName, $OSType){
	Initialize-Environment -AzureSecretsFile $AzureSecretsFile -logFileName "Install-CustomScriptOnAllVMs.log"

	$uriArray = $FileUris -split ","
	$settings =  @{"fileUris" = $uriArray; "commandToExecute" = $CommandToRun}
	$protectedSettings = @{}
	if ($StorageAccountKey -and $StorageAccountName) {
		$protectedSettings = @{"storageAccountName" = $StorageAccountName; "storageAccountKey" = $StorageAccountKey}
	}

	if ($OSType -eq "Linux") {
		$extensionName = "CustomScript"
		$extensionPublisher = "Microsoft.Azure.Extensions"
		$extensionVersion = "2.0"
	} else {
		$extensionName = "CustomScriptExtension"
		$extensionPublisher = "Microsoft.Compute"
		$extensionVersion = "1.9"
	}

	$vms = @()
	if ($ResourceGroupName -and $VmName) {
		$vms += Get-AzureRmVM -ResourceGroupName $ResourceGroupName -Name $VmName
	} elseif ($ResourceGroupName) {
		$vms = Get-AzureRmVM -ResourceGroupName $ResourceGroupName | Where-Object {$_.StorageProfile.OsDisk.OsType -eq $OSType}
	} else {
		$vms = Get-AzureRmVM | Where-Object {$_.StorageProfile.OsDisk.OsType -eq $OSType}
	}
	$jobs = @()
	$jobIdToVM = @{}
	$vmsNotRunning = @()
	$vmsAgentUnresponsive = @()
	foreach ($vm in $VMs) {
		try {
			$vmStatus = Get-AzureRmVM -ResourceGroupName $vm.ResourceGroupName -Name $vm.Name -Status
			if ($vmStatus.Statuses[1].Code -inotmatch "running") {
				$vmsNotRunning += $vm
				continue
			}
			if ($vmStatus.VMAgent.VmAgentVersion -imatch "Unknown") {
				$vmsAgentUnresponsive += $vm
				continue
			}
			# Only install the extenstion on VMs running and has waagent installed
			$extension = Get-AzureRmVMExtension -ResourceGroupName $vm.ResourceGroupName -VMName $vm.Name -Name $extensionName -ErrorAction SilentlyContinue
			if ($extension -and $extension.PublicSettings -imatch $FileUris -and $extension.PublicSettings -imatch $CommandToRun) {
				# CustomScript extension is already installed
				Write-LogInfo "Custom script is already installed on VM $($vm.Name) in $($vm.ResourceGroupName)."
				continue
			}
			Write-LogInfo "Start to install CustomScript extension on VM $($vm.Name) in resource group $($vm.ResourceGroupName)"
			$job = Set-AzureRmVMExtension -ResourceGroupName $vm.ResourceGroupName -VMName $vm.Name -Location $vm.Location -Name $extensionName -Publisher $extensionPublisher `
				-Type $extensionName -TypeHandlerVersion $extensionVersion -Settings $settings -ProtectedSettings $protectedSettings -AsJob
			$jobs += $job
			$jobIdToVM[$job.Id] = $vm
		} catch {
			Write-LogErr "Exception occurred in when installing CustomScript extension on VM $($vm.Name)."
			Write-LogErr $_.Exception
		}
	}
	$jobs | Wait-Job -Timeout 360
	foreach ($job in $jobs) {
		$state = $job.State
		if ($state -eq "Running") {
			$state = "Timeout"
			Stop-Job -Job $job
		}
		Write-LogInfo "Installation on VM $($jobIdToVM[$job.Id].Name) in resource group $($jobIdToVM[$job.Id].ResourceGroupName): $state"
	}

	Write-LogInfo "CustomScript extension is newly installed on $($jobs.Count) VMs among $($VMs.Count) $OSType VMs in the subscription`n"
	if ($vmsNotRunning.Count -gt 0) {
		Write-LogWarn "CustomScript extension is not installed on $($vmsNotRunning.Count) $OSType VMs due to VM not running`n"
	}
	if ($vmsAgentUnresponsive.Count -gt 0) {
		Write-LogWarn "CustomScript extension is not installed on the following $($vmsAgentUnresponsive.Count) $OSType VMs due to VM agent is unresponsive:`n"
		foreach ($vm in $vmsAgentUnresponsive) {
			Write-LogInfo "VM $($vm.Name) in resource group $($vm.ResourceGroupName): VM agent unresponsive"
		}
	}
}

Install-CustomScript -AzureSecretsFile $AzureSecretsFile -FileUris $FileUris -CommandToRun $CommandToRun -StorageAccountName $StorageAccountName `
	-StorageAccountKey $StorageAccountKey -VmName $VmName -ResourceGroupName $ResourceGroupName -OSType $OSType