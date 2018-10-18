##############################################################################################
# UpdateNestedTestParameters.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.SYNOPSIS
    Update test parameters for nested vm test case

.PARAMETER 
    <Parameters>

.INPUTS


.NOTES
    Creation Date:  23th July 2018

.EXAMPLE

#>
###############################################################################################

param(
	[string]$TestName = "",
	[string]$NestedImageUrl = "",
	[string]$NestedUser = "",
	[string]$NestedUserPassword = "",
	[string]$RaidOption = "",
	[string]$setupType = ""
)

$TestXMLs = Get-ChildItem -Path ".\XML\TestCases\*.xml"
foreach ( $file in $TestXMLs.FullName)
{
	$TestXmlConfig = [xml]( Get-Content -Path $file)
	foreach ( $test in $TestXmlConfig.TestCases.test )
	{
		if ( $test.Tags.ToString().Contains("nested") -and ( $TestName.Split(',').contains($($test.TestName)) ) )
		{
			Write-Host "Update test parameters for case $($test.TestName)"
			foreach ($param in $test.TestParameters.ChildNodes)
			{
				if ( $param."#text" -match 'NestedImageUrl=' )
				{
					$param."#text" = "NestedImageUrl=$NestedImageUrl"
				}
				if ( $param."#text" -match 'NestedUser=' )
				{
					$param."#text" = "NestedUser=$NestedUser"
				}
				if ( $param."#text" -match 'NestedUserPassword=' )
				{
					$param."#text" = "NestedUserPassword='$NestedUserPassword'"
				}
				if ( $param."#text" -match 'RaidOption=' )
				{
					$param."#text" = "RaidOption='$RaidOption'"
				}
			}
			if ($setupType)
			{
				Write-Host "Update test setup type: $setupType"
				$test.setupType = $setupType
			}
		}
	}
	$TestXmlConfig.save($file)
}