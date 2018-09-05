# Linux on Hyper-V and Azure Test Code, ver. 1.0.0
# Copyright (c) Microsoft Corporation

# Description: This script displays the LISav2 test case statistics and list of available tags.

# Read all test case xml files
$files = Get-ChildItem XML\TestCases\*.xml

$azure_only = 0
$hyperv_only = 0
$both_platforms = 0

# Hashtab for tag info collection
$tags = @{}

Write-Output ""
"{0,-60} {1,20} {2,15} {3,15} {4,40}" -f "TestCase", "Platform", "Category", "Area", "Tags"
Write-Output "----------------------------------------------------------------------------------------------------------------------------------------------------------"

foreach ($fname in $files) {
    $xml = [xml](Get-Content $fname)
    foreach ($item in $xml.TestCases.test) {
        "{0,-60} {1,20} {2,15} {3,15} {4,40}" -f $item.testName, $item.Platform, $item.Category, $item.Area, $item.Tags

        # Group per platform type
        if ($item.Platform -eq "HyperV") {
            $hyperv_only++
        } elseif ($item.Platform -eq "Azure") {
            $azure_only++
        } else {
            $both_platforms++
        }

        # Update tag hashtable
        foreach ($single_tag in $item.Tags.Split(",")) {
            if ($tags.ContainsKey($single_tag)) {
                $tags[$single_tag]++
            } else {
                $tags.Add($single_tag, 1)
            }

        }
    }
}

# Show the statistics information
Write-Output ""
Write-Output "===== Test Cases counts per platform ====="
Write-Output ""
Write-Output "Azure only: $azure_only"
Write-Output "Hyper-V only: $hyperv_only"
Write-Output "Both platforms: $both_platforms"
Write-Output ""
Write-Output "===== Tag Details ====="

# Show tag information
$tags