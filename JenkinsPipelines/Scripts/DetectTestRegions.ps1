##############################################################################################
# DetectTestRegions.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	<Description>

.PARAMETER
	<Parameters>

.INPUTS
	

.NOTES
    Creation Date:  
    Purpose/Change: 

.EXAMPLE


#>
###############################################################################################

param
(
    $TestByTestName="",
    $TestByCategorizedTestName="",
    $TestByCategory="",
    $TestByTag=""
)
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

$TestRegions = @()

if ( $TestByTestName )
{
    foreach( $Test in $TestByTestName.Split(","))
    {
        $TestRegions += $Test.Split(">>")[$Test.Split(">>").Count - 1]
    }
}
if ( $TestByCategorizedTestName )
{
    foreach( $Test in $TestByCategorizedTestName.Split(","))
    {
        $TestRegions += $Test.Split(">>")[$Test.Split(">>").Count - 1]
    }
}
if ( $TestByCategory )
{
    foreach( $Test in $TestByCategory.Split(","))
    {
        $TestRegions += $Test.Split(">>")[$Test.Split(">>").Count - 1]
    }
}
if ( $TestByTag )
{
    foreach( $Test in $TestByTag.Split(","))
    {
        $TestRegions += $Test.Split(">>")[$Test.Split(">>").Count - 1]
    }
}

$UniqueTestRegions = $TestRegions | Sort-Object |  Get-Unique
LogMsg "Selected test regions:"
$i = 1
$CurrentTestRegions = ""
Set-Content -Value "" -Path .\CurrentTestRegions.azure.env -Force -NoNewline
$UniqueTestRegions | ForEach-Object { LogMsg "$i. $_"; $i += 1; $CurrentTestRegions += "$_," }
Set-Content -Value $CurrentTestRegions.TrimEnd(",") -Path .\CurrentTestRegions.azure.env -Force -NoNewline -Verbose