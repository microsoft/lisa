
Param(
    $DestinationPath = ".\"
)

Get-ChildItem .\TestLibs\*.psm1 | ForEach-Object { Import-Module $_.FullName -Force}
ValiateXMLs -ParentFolder ".\"

$xmlData = @()
foreach ( $file in (Get-ChildItem -Path .\XML\TestCases\*.xml ))
{
    $xmlData += ([xml](Get-Content -Path $file.FullName)).TestCases
}
$TestToRegionMapping = ([xml](Get-Content .\XML\TestToRegionMapping.xml))
#Get Unique Platforms
$Platforms = $xmlData.test.Platform.Split(',')  | Sort-Object | Get-Unique
Write-Host $Platforms
$Categories = $xmlData.test.Category | Sort-Object | Get-Unique
Write-Host $Categories
$Areas =$xmlData.test.Area | Sort-Object | Get-Unique
Write-Host $Areas
$Tags =$xmlData.test.Tags.Split(",") | Sort-Object | Get-Unique
Write-Host $Tags
$TestNames = $xmlData.testName | Sort-Object | Get-Unique
Write-Host $TestNames


$JenkinsMenuFile =  "platform`tcategory`tarea`tregion`n"
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
                        Write-Host "foreach ( $arearegion in $AreaRegions )"
                        if ( $Regions.Contains($arearegion))
                        {
                            Write-Host "if ( $Regions.Contains($arearegion))"
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
                $JenkinsMenuFile += "$platform`t$category`t$area`t$platform>>$category>>$area>>$region`n"
            }
        }
        if ( $(($Areas | Get-Unique).Count) -gt 1)
        {
            foreach ( $region in $Regions)
            {
                $JenkinsMenuFile += "$platform`t$category`tAll`t$platform>>$category>>All>>$region`n"
            }
        }
    }
    if ( $(($Categories | Get-Unique).Count) -gt 1)
    {
        foreach ( $region in $Regions)
        {
            $JenkinsMenuFile += "$platform`tAll`tAll`t$platform>>All>>All>>$region`n"
        }
    }
}

Set-Content -Value $JenkinsMenuFile -Path "$DestinationPath\JenkinsMenuFile.txt" -Force
(Get-Content "$DestinationPath\JenkinsMenuFile.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\JenkinsMenuFile.txt"


$tagsFile = "platform`ttag`tregion`n"
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
                $tagsFile += "$platform`t$tag`t$platform>>$tag>>$region`n"
            }
        }
    }
}
Set-Content -Value $tagsFile -Path "$DestinationPath\JenkinsMenuFile4.txt" -Force
(Get-Content "$DestinationPath\JenkinsMenuFile4.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\JenkinsMenuFile4.txt"


$testnameFile = "platform`ttestname`tregion`n"
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
                $testnameFile += "$platform`t$testname`t$region`n"
            }
        }
    }
}
Set-Content -Value $testnameFile -Path "$DestinationPath\JenkinsMenuFile3.txt" -Force
(Get-Content "$DestinationPath\JenkinsMenuFile3.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\JenkinsMenuFile3.txt"



$JenkinsMenuFile2 =  "platform`tcategory`tarea`ttestname`tregion`n"
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
                    #Write-Host "$platform`t$category`t$area`t$testname`t$region"
                    $JenkinsMenuFile2 += "$platform`t$category`t$area`t$testname`t$platform>>$category>>$area>>$testname>>$region`n"
                }
            }
        }
    }
}
Write-Host "Setting Content"
Set-Content -Value $JenkinsMenuFile2 -Path "$DestinationPath\JenkinsMenuFile2.txt" -Force
Write-Host "Replacing whitespaces"
(Get-Content "$DestinationPath\JenkinsMenuFile2.txt") | Where-Object {$_.trim() -ne "" } | set-content "$DestinationPath\JenkinsMenuFile2.txt"
Write-Host "Completed."

exit 0