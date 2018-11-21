##############################################################################################
# WorkingSpaceManagement.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation.
	When LISAv2 is running, some files may be created with multiple layer of folders;
	in such cases, the total length of the file path may be too long for Windows to handle.
	So, LISAv2 will try to find a folder with short folder path as its working directory. 

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Function Move-ToNewWorkingSpace($originalFolder) {
	Write-Host "Current working directory '$originalFolder' path length is too long."
	$tempWorkspace    = "$(Split-Path $originalFolder -Qualifier)"
	$tempParentFolder = "$tempWorkspace\LISAv2"
	$tempWorkingDir   = "$tempWorkspace\LISAv2\$TestID"

	New-Item -ItemType Directory -Path $tempParentFolder -Force -ErrorAction SilentlyContinue | Out-Null
	New-Item -ItemType Directory -Path $tempWorkingDir   -Force -ErrorAction SilentlyContinue | Out-Null
	$tmpSource = '\\?\' + "$originalFolder\*"
	Write-Host "Copying current workspace to $tempWorkingDir"
	$excludedDirectories = @(".git", "Documents", ".github", "Report", "TestResults", "VHDs_Destination_Path", "*.zip")
	Copy-Item -Path $tmpSource -Destination $tempWorkingDir -Recurse -Force -Exclude $excludedDirectories | Out-Null
	Set-Location -Path $tempWorkingDir | Out-Null
	Write-Host "Working directory has been changed to $tempWorkingDir"
	return $tempWorkingDir
}

Function Move-BackToOriginalWorkingSpace($currentWorkingDirectory, $OriginalWorkingDirectory){
	Write-Host "Copying all files back to original working directory: $OriginalWorkingDirectory."
	$tmpDest = '\\?\' + $OriginalWorkingDirectory
	Copy-Item -Path "$currentWorkingDirectory\*" -Destination $tmpDest -Force -Recurse | Out-Null
	Set-Location ..
	Write-Host "Cleaning up $currentWorkingDirectory"
	Remove-Item -Path $currentWorkingDirectory -Force -Recurse -ErrorAction SilentlyContinue
	Write-Host "Setting workspace back to original location: $originalWorkingDirectory"
	Set-Location $originalWorkingDirectory
}