# Linux on Hyper-V and Azure Test Code, ver. 1.0.0
# Copyright (c) Microsoft Corporation

# Description: This script displays the LISav2 test case statistics and list of available tags.

# Read all test case xml files
param (
    [string] $Platform,
    [string] $Tags,
    [ValidateSet("0", "1", "2", "3")]
    [string] $Priority,
    [string] $Category,
    [string] $Area,
    [switch] $ExportCSV,
    [string] $Path
)

# Hashtable for tag info collection
$numTags = @{}

$currentPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$files = Get-ChildItem (Join-Path $currentPath "..\XML\TestCases\*.xml") -Exclude Other.xml

$all_test_cases = @()
$platform_info = @{}
foreach ($fname in $files) {
    $xml = [xml](Get-Content $fname)
    foreach ($item in $xml.TestCases.test) {

        $all_test_cases += $item

        # Group per platform type
        if ($item.Platform -like "*,*") {
            $platforms = $item.Platform.Split(",") | Sort-Object
            $platforms = $platforms -join ', '
            $platform_info[$platforms + ':']++
        } else {
            $platform_info[$item.Platform + " only:"]++
        }
        # Update tag hashtable
        foreach ($singleTag in $item.Tags.Split(",")) {
            if ($numTags.ContainsKey($singleTag)) {
                $numTags[$singleTag]++
            } else {
                $numTags.Add($singleTag, 1)
            }
        }
    }
}

if ($Platform) {
    $all_test_cases = @($all_test_cases | Where-Object {$_.Platform -imatch $Platform})
}

if ($Priority) {
    $all_test_cases = @($all_test_cases | Where-Object {$_.Priority -imatch $Priority})
}

if ($Tags) {
    $all_test_cases = @($all_test_cases | Where-Object {$_.Tags -imatch $Tags})
}

if ($Category) {
    $all_test_cases = @($all_test_cases | Where-Object {$_.Category -imatch $Category})
}

if ($Area) {
    $all_test_cases = @($all_test_cases | Where-Object {$_.Area -imatch $Area})
}

if ($ExportCSV.IsPresent) {
    if (!$Path){
        $Path = "./LISAv2Statistics_" + (Get-Date).ToString("yyyyMMdd_hhmmss") + ".csv"
    }
    $all_test_cases | Select-Object -Property TestName,Platform,Category,Area,Tags,Priority | Export-Csv -Path $Path -NoTypeInformation -Force
    if ($?) {
        Write-Output "Exported CSV file: $Path"
    }
}
else {
    if ($Path) {
        Write-Output "`n[Warning]: '-Path' has value '$Path', but '-ExportCSV' does NOT present as a parameter, hence formating output as Table instead of exporting csv."
        Start-Sleep -s 5
    }
    $all_test_cases | Format-Table TestName,Platform,Category,Area,Tags,Priority -AutoSize
    Write-Output "TestCases Count: $($all_test_cases.count)"

    if (!$Platform -and !$Priority -and !$Tags -and !$Category -and !$Area) {
        Write-Output "===== Test Cases Number per platform ====="
        $platform_info | Format-Table -hide
        Write-Output "===== Tag Details ====="
        #Show tag information
        Write-Output ($numTags | Out-String)
    }
}