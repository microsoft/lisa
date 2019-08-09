##############################################################################################
# JenkinsTestSelectionMenuGenerator.ps1
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

Param(
    $LogFileName = "JenkinsTestSelectionMenuGenerator.log",
    $DestinationPath = ".\"
)

Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }
Validate-XmlFiles -ParentFolder ".\"

$xmlData = @()
foreach ( $file in (Get-ChildItem -Path .\XML\TestCases\*.xml ))
{
    $xmlData += ([xml](Get-Content -Path $file.FullName)).TestCases
}
$TestToRegionMapping = ([xml](Get-Content .\XML\TestToRegionMapping.xml))

#Get Unique Platforms
$Platforms = $xmlData.test.Platform.Split(',')  | Sort-Object | Get-Unique
Write-LogInfo "ALL TEST PLATFORMS"
Write-LogInfo "--------------"
$i = 1; $Platforms | ForEach-Object { Write-LogInfo "$i. $($_)"; $i++ }

$Categories = $xmlData.test.Category | Sort-Object | Get-Unique
Write-LogInfo "ALL TEST CATEGORIES"
Write-LogInfo "----------------"
$i = 1; $Categories | ForEach-Object { Write-LogInfo "$i. $($_)"; $i++ }

$Areas =$xmlData.test.Area | Sort-Object | Get-Unique
Write-LogInfo "ALL TEST AREAS"
Write-LogInfo "----------"
$i = 1; $Areas | ForEach-Object { Write-LogInfo "$i. $($_)"; $i++ }

$TestNames = $xmlData.test.testName | Sort-Object | Get-Unique
Write-LogInfo "ALL TEST NAMES"
Write-LogInfo "----------"
$i = 1; $TestNames | ForEach-Object { Write-LogInfo "$i. $($_)"; $i++ }

$Tags =$xmlData.test.Tags.Split(",") | Sort-Object | Get-Unique
Write-LogInfo "TEST TAGS"
Write-LogInfo "---------"
$i = 1; $Tags | ForEach-Object { Write-LogInfo "$i. $($_)"; $i++ }

$TestByCategory =  "platform`tcategory`tarea`tregion`n"

# Generate Jenkins File
foreach ( $platform in $Platforms )
{
    $CurrentCategories = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) }).Category | Sort-Object | Get-Unique
    foreach ( $category in $CurrentCategories)
    {
       if ( $TestToRegionMapping.enabledRegions.Category.$category )
        {
            $CurrentRegions = ($TestToRegionMapping.enabledRegions.Category.$category).Split(",")
        }
        else
        {
            $CurrentRegions =$TestToRegionMapping.enabledRegions.global.Split(",")
        }
        $CurrentAreas = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) } | Where-Object { $_.Category -eq "$category" }).Area | Sort-Object | Get-Unique
        foreach ($area in $CurrentAreas)
        {
            foreach ( $region in $CurrentRegions)
            {
                $TestByCategory += "$platform`t$category`t$area`t$platform>>$category>>$area>>$region`n"
            }
        }
    }
}

Write-LogInfo "Saving TestByCategory.txt..."
Set-Content -Value $TestByCategory -Path "$DestinationPath\TestByCategory.txt" -Force
Write-LogInfo "Validating TestByCategory.txt..."
(Get-Content "$DestinationPath\TestByCategory.txt") | Where-Object {$_.trim() -ne "" } | Set-Content "$DestinationPath\TestByCategory.txt"
Write-LogInfo "Done"

$TestsByTag = "platform`ttag`tregion`n"
foreach ( $platform in $Platforms )
{
    foreach ( $tag in $Tags)
    {
        $Regions =$TestToRegionMapping.enabledRegions.global.Split(",")
        if ( $tag )
        {
            if ( $TestToRegionMapping.enabledRegions.Tag.$tag )
            {
                $Regions = ($TestToRegionMapping.enabledRegions.Tag.$tag).Split(",")
            }
            foreach ( $region in $Regions)
            {
                $TestsByTag += "$platform`t$tag`t$platform>>$tag>>$region`n"
            }
        }
    }
}

Write-LogInfo "Saving TestsByTag.txt..."
Set-Content -Value $TestsByTag -Path "$DestinationPath\TestsByTag.txt" -Force
Write-LogInfo "Validating TestsByTag.txt..."
(Get-Content "$DestinationPath\TestsByTag.txt") | Where-Object {$_.trim() -ne "" } | Set-Content "$DestinationPath\TestsByTag.txt"
Write-LogInfo "Done"

$TestByTestnameQuick = "platform`ttestname`tregion`n"
foreach ( $platform in $Platforms )
{
    $TestNames = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) } ).TestName | Sort-Object | Get-Unique
    foreach ( $testname in $TestNames)
    {

        if ( $TestToRegionMapping.enabledRegions.TestName.$testname )
        {
            $Regions = ($TestToRegionMapping.enabledRegions.TestName.$testname).Split(",")
        }
        else
        {
            $Regions =$TestToRegionMapping.enabledRegions.global.Split(",")
        }
        foreach ( $region in $Regions)
        {
            $TestByTestnameQuick += "$platform`t$testname`t$platform>>$testname>>$region`n"
        }
    }
}

Write-LogInfo "Saving TestByTestnameQuick.txt..."
Set-Content -Value $TestByTestnameQuick -Path "$DestinationPath\TestByTestnameQuick.txt" -Force
Write-LogInfo "Validating TestByTestnameQuick.txt..."
(Get-Content "$DestinationPath\TestByTestnameQuick.txt") | Where-Object {$_.trim() -ne "" } | Set-Content "$DestinationPath\TestByTestnameQuick.txt"
Write-LogInfo "Done"

$TestByTestnameDetailed =  "platform`tcategory`tarea`ttestname`tregion`n"

# Generate Jenkins file
foreach ( $platform in $Platforms )
{
    $CurrentCategories = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) }).Category | Sort-Object | Get-Unique
    foreach ( $category in $CurrentCategories)
    {
        $CurrentAreas = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) } | Where-Object { $_.Category -eq "$category" }).Area | Sort-Object | Get-Unique
        foreach ($area in $CurrentAreas)
        {
            $TestNames = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) } | Where-Object { $_.Category -eq "$category" } | Where-Object { $_.Area -eq "$area" } ).TestName | Sort-Object | Get-Unique
            foreach ( $testname in $TestNames )
            {
                if ( $TestToRegionMapping.enabledRegions.TestName.$testname )
                {
                    $CurrentRegions = ($TestToRegionMapping.enabledRegions.TestName.$testname).Split(",")
                }
                else
                {
                    $CurrentRegions =$TestToRegionMapping.enabledRegions.global.Split(",")
                }
                foreach ( $region in $CurrentRegions)
                {
                    $TestByTestnameDetailed += "$platform`t$category`t$area`t$testname`t$platform>>$category>>$area>>$testname>>$region`n"
                }
            }
        }
    }
}

Write-LogInfo "Saving TestByTestnameDetailed.txt..."
Set-Content -Value $TestByTestnameDetailed -Path "$DestinationPath\TestByTestnameDetailed.txt" -Force
Write-LogInfo "Validating TestByTestnameDetailed.txt..."
(Get-Content "$DestinationPath\TestByTestnameDetailed.txt") | Where-Object {$_.trim() -ne "" } | Set-Content "$DestinationPath\TestByTestnameDetailed.txt"
Write-LogInfo "Done"


# This file is created for job: pipeline-cloudtest-manual
# Parameter Name : CATEGORY_AREA
$AzureCategoryAreas =  "CategoryArea="
foreach ( $platform in $Platforms )
{
    if ($platform -ne "Azure") {
        continue;
    }
    $CurrentCategories = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) }).Category | Sort-Object | Get-Unique
    foreach ( $category in $CurrentCategories)
    {
        $CurrentAreas = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) } | Where-Object { $_.Category -eq "$category" }).Area | Sort-Object | Get-Unique
        foreach ($area in $CurrentAreas)
        {
            if ($category -and $area) {
                $AzureCategoryAreas += "$category $area,"
            }
        }
    }
}
$AzureCategoryAreas = $AzureCategoryAreas.Trim(",")
$FilePath = "$DestinationPath\Azure-LISAv2-TestCategoryAreas.txt"
Write-LogInfo "Saving $FilePath..."
Set-Content -Value $AzureCategoryAreas -Path $FilePath -Force
Write-LogInfo "Validating $FilePath..."
(Get-Content $FilePath) | Where-Object {$_.trim() -ne "" } | Set-Content -Path $FilePath -Force -NoNewline
Write-LogInfo "Done."

# This file is created for job: pipeline-cloudtest-manual
# Parameter Name : TEST_NAMES
$AzureTestNames =  "TestNames="
foreach ( $platform in $Platforms )
{
    if ($platform -ne "Azure") {
        continue;
    }
    $TestNames = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) }).TestName | Sort-Object | Get-Unique
    foreach ( $testname in $TestNames )
    {
        if ($testname -imatch "CAPTURE-VHD") {
            continue;
        }
        $AzureTestNames += "$testname,"
    }
}
$AzureTestNames = $AzureTestNames.Trim(",")
$FilePath = "$DestinationPath\Azure-LISAv2-TestNames.txt"
Write-LogInfo "Saving $FilePath..."
Set-Content -Value $AzureTestNames -Path $FilePath -Force
Write-LogInfo "Validating $FilePath..."
(Get-Content $FilePath) | Where-Object {$_.trim() -ne "" } | Set-Content -Path $FilePath -Force -NoNewline
Write-LogInfo "Done."

Write-LogInfo "Saving '$($env:GitRepo)' to DefaultGitRepo.txt..."
Set-Content -Value "DefaultGitRepo=$($env:GitRepo)"  -Path "$DestinationPath\DefaultGitRepo.txt" -Force -NoNewline

Write-LogInfo "Saving '$($env:GitBranch)' to DefaultGitBranch.txt..."
Set-Content -Value "DefaultGitBranch=$($env:GitBranch)"  -Path "$DestinationPath\DefaultGitBranch.txt" -Force -NoNewline

exit 0
