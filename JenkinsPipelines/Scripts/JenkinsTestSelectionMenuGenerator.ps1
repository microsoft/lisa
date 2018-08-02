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
    $DestinationPath = ".\"
)
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }
ValidateXmlFiles -ParentFolder ".\"

$xmlData = @()
foreach ( $file in (Get-ChildItem -Path .\XML\TestCases\*.xml ))
{
    $xmlData += ([xml](Get-Content -Path $file.FullName)).TestCases
}
$TestToRegionMapping = ([xml](Get-Content .\XML\TestToRegionMapping.xml))
#Get Unique Platforms

$Platforms = $xmlData.test.Platform.Split(',')  | Sort-Object | Get-Unique
LogMsg "ALL TEST PLATFORMS"
LogMsg "--------------"
$i = 1; $Platforms | ForEach-Object { LogMsg "$i. $($_)"; $i++ }

$Categories = $xmlData.test.Category | Sort-Object | Get-Unique
LogMsg "ALL TEST CATEGORIES"
LogMsg "----------------"
$i = 1; $Categories | ForEach-Object { LogMsg "$i. $($_)"; $i++ }

$Areas =$xmlData.test.Area | Sort-Object | Get-Unique
LogMsg "ALL TEST AREAS"
LogMsg "----------"
$i = 1; $Areas | ForEach-Object { LogMsg "$i. $($_)"; $i++ }

$TestNames = $xmlData.test.testName | Sort-Object | Get-Unique
LogMsg "ALL TEST NAMES"
LogMsg "----------"
$i = 1; $TestNames | ForEach-Object { LogMsg "$i. $($_)"; $i++ }

$Tags =$xmlData.test.Tags.Split(",") | Sort-Object | Get-Unique
LogMsg "TEST TAGS"
LogMsg "---------"
$i = 1; $Tags | ForEach-Object { LogMsg "$i. $($_)"; $i++ }


$TestByCategory =  "platform`tcategory`tarea`tregion`n"
#Generate Jenkins File
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

LogMsg "Saving TestByCategory.txt..."
Set-Content -Value $TestByCategory -Path "$DestinationPath\TestByCategory.txt" -Force
LogMsg "Validating TestByCategory.txt..."
(Get-Content "$DestinationPath\TestByCategory.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\TestByCategory.txt"
LogMsg "Done"

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
LogMsg "Saving TestsByTag.txt..."
Set-Content -Value $TestsByTag -Path "$DestinationPath\TestsByTag.txt" -Force
LogMsg "Validating TestsByTag.txt..."
(Get-Content "$DestinationPath\TestsByTag.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\TestsByTag.txt"
LogMsg "Done"


$TestByTestnameQuick = "platform`ttestname`tregion`n"
foreach ( $platform in $Platforms )
{
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

LogMsg "Saving TestByTestnameQuick.txt..."
Set-Content -Value $TestByTestnameQuick -Path "$DestinationPath\TestByTestnameQuick.txt" -Force
LogMsg "Validating TestByTestnameQuick.txt..."
(Get-Content "$DestinationPath\TestByTestnameQuick.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\TestByTestnameQuick.txt"
LogMsg "Done"


$TestByTestnameDetailed =  "platform`tcategory`tarea`ttestname`tregion`n"
#Generate Jenkins File
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

LogMsg "Saving TestByTestnameDetailed.txt..."
Set-Content -Value $TestByTestnameDetailed -Path "$DestinationPath\TestByTestnameDetailed.txt" -Force
LogMsg "Validating TestByTestnameDetailed.txt..."
(Get-Content "$DestinationPath\TestByTestnameDetailed.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\TestByTestnameDetailed.txt"
LogMsg "Done"

LogMsg "Saving '$($env:GitRepo)' to DefaultGitRepo.txt..."
Set-Content -Value "DefaultGitRepo=$($env:GitRepo)"  -Path "$DestinationPath\DefaultGitRepo.txt" -Force -NoNewline

LogMsg "Saving '$($env:GitBranch)' to DefaultGitBranch.txt..."
Set-Content -Value "DefaultGitBranch=$($env:GitBranch)"  -Path "$DestinationPath\DefaultGitBranch.txt" -Force -NoNewline

exit 0