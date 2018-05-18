
Param(
    $DestinationPath = ".\"
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }
ValiateXMLs -ParentFolder ".\"

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
    $Categories = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) }).Category
    foreach ( $category in $Categories)
    {
        $Regions =$TestToRegionMapping.enabledRegions.global.Split(",")
        $Areas = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) } | Where-Object { $_.Category -eq "$category" }).Area
        if ( $TestToRegionMapping.enabledRegions.Category.$category )
        {
            $Regions = ($TestToRegionMapping.enabledRegions.Category.$category).Split(",")
        }
        foreach ($area in $Areas)
        {
            if ( [string]::IsNullOrEmpty($TestToRegionMapping.enabledRegions.Category.$category))
            {
                if ($TestToRegionMapping.enabledRegions.Area.$area)
                {
                    $Regions = ($TestToRegionMapping.enabledRegions.Area.$area).Split(",")
                }
            }
            else
            {
                $Regions = ($TestToRegionMapping.enabledRegions.Category.$category).Split(",")
                if ( $TestToRegionMapping.enabledRegions.Area.$area )
                {
                    $tempRegions = @()
                    $AreaRegions = ($TestToRegionMapping.enabledRegions.Area.$area).Split(",")
                    foreach ( $arearegion in $AreaRegions )
                    {
                        LogMsg "foreach ( $arearegion in $AreaRegions )"
                        if ( $Regions.Contains($arearegion))
                        {
                            LogMsg "if ( $Regions.Contains($arearegion))"
                            $tempRegions += $arearegion
                        }
                    }
                    if ( $tempRegions.Count -ge 1)
                    {
                        $Regions = $tempRegions
                    }
                    else
                    {
                        $Regions = "no_region_available"
                    }
                }
            }
            foreach ( $region in $Regions)
            {
                $TestByCategory += "$platform`t$category`t$area`t$platform>>$category>>$area>>$region`n"
            }
        }
        if ( $(($Areas | Get-Unique).Count) -gt 1)
        {
            foreach ( $region in $Regions)
            {
                $TestByCategory += "$platform`t$category`tAll`t$platform>>$category>>All>>$region`n"
            }
        }
    }
    if ( $(($Categories | Get-Unique).Count) -gt 1)
    {
        foreach ( $region in $Regions)
        {
            $TestByCategory += "$platform`tAll`tAll`t$platform>>All>>All>>$region`n"
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

<#
$TestByTestName = "platform`ttestname`tregion`n"
foreach ( $platform in $Platforms )
{
    foreach ( $testname in $TestNames)
    {
        $Regions =$TestToRegionMapping.enabledRegions.global.Split(",")
        if ( $TestToRegionMapping.enabledRegions.TestName.$testname )
        {
            $Regions = ($TestToRegionMapping.enabledRegions.TestName.$testname).Split(",")
        }
        if ( $testname )
        {
            foreach ( $region in $Regions)
            {
                $TestByTestName += "$platform`t$testname`t$region`n"
            }
        }
    }
}
Set-Content -Value $TestByTestName -Path "$DestinationPath\JenkinsMenuFile3.txt" -Force
(Get-Content "$DestinationPath\JenkinsMenuFile3.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\JenkinsMenuFile3.txt"
#>

$TestByTestname =  "platform`tcategory`tarea`ttestname`tregion`n"
#Generate Jenkins File
foreach ( $platform in $Platforms )
{
    $Categories = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) }).Category
    foreach ( $category in $Categories)
    {
        $Regions =$TestToRegionMapping.enabledRegions.global.Split(",")
        $Areas = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) } | Where-Object { $_.Category -eq "$category" }).Area
        if ( $TestToRegionMapping.enabledRegions.Category.$category )
        {
            $Regions = ($TestToRegionMapping.enabledRegions.Category.$category).Split(",")
        }
        foreach ($area in $Areas)
        {
            if ( [string]::IsNullOrEmpty($TestToRegionMapping.enabledRegions.Category.$category))
            {
                if ($TestToRegionMapping.enabledRegions.Area.$area)
                {
                    $Regions = ($TestToRegionMapping.enabledRegions.Area.$area).Split(",")
                }
            }
            else
            {
                $Regions = ($TestToRegionMapping.enabledRegions.Category.$category).Split(",")
                if ( $TestToRegionMapping.enabledRegions.Area.$area )
                {
                    $tempRegions = @()
                    $AreaRegions = ($TestToRegionMapping.enabledRegions.Area.$area).Split(",")
                    foreach ( $arearegion in $AreaRegions )
                    {
                        if ( $Regions.Contains($arearegion))
                        {
                            $tempRegions += $arearegion
                        }
                    }
                    if ( $tempRegions.Count -ge 1)
                    {
                        $Regions = $tempRegions
                    }
                    else
                    {
                        $Regions = "no_region_available"
                    }
                }
            }
            $TestNames = ($xmlData.test | Where-Object { $_.Platform.Contains($platform) } | Where-Object { $_.Category -eq "$category" } | Where-Object { $_.Area -eq "$area" } ).TestName
            foreach ( $testname in $TestNames )
            {
                $Regions =$TestToRegionMapping.enabledRegions.global.Split(",")
                if ( $TestToRegionMapping.enabledRegions.TestName.$testname )
                {
                    $Regions = ($TestToRegionMapping.enabledRegions.TestName.$testname).Split(",")
                }
                foreach ( $region in $Regions)
                {
                    #LogMsg "$platform`t$category`t$area`t$testname`t$region"
                    $TestByTestname += "$platform`t$category`t$area`t$testname`t$platform>>$category>>$area>>$testname>>$region`n"
                }
            }
        }
    }
}
LogMsg "Saving TestByTestname.txt..."
Set-Content -Value $TestByTestname -Path "$DestinationPath\TestByTestname.txt" -Force
LogMsg "Validating TestByTestname.txt..."
(Get-Content "$DestinationPath\TestByTestname.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\TestByTestname.txt"
LogMsg "Done"
exit 0