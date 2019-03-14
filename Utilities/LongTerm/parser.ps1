# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param (
    [String] $LogType,
    [String] $LogPath
)

$SUPPORTED_TYPES = @("vmstat", "iostat", "mpstat", "sysbench", "sar")
if ($SUPPORTED_TYPES.IndexOf($LogType) -eq -1) {
    Write-Host "Log type: $LogType not supported"
}

function parse_vmstat {
    param (
        [array] $content
    )

    $LINE_MATCHES = @{"CAT_SUMMARY" = "(?=.*procs)(?=.*memory)";
                      "CATEGORY" = "(?=.* r )(?=.* swpd )(?=.* free )(?=.* buff )";
                      "VALUES" = "\d"}

    $VALUES = New-Object System.Collections.Generic.List[System.Object]
    $CATEGORIES = @()

    foreach ($line in $content) {
        $lineType = ""
        foreach ($key in $LINE_MATCHES.Keys) {
            if ($line -match $LINE_MATCHES[$key]) {
                $lineType = $key
                break
            }
        }
        switch ($lineType) {
            "" {
                # Write-Host "Warning: Line does not match anything"
                break
            }
            "CATEGORY" {
                $CATEGORIES = ($line -replace '\s+', ' ').split(" ")
                $CATEGORIES[-1] = "DATE"
                break
            }
            "VALUES" {
                $vals = ($line -replace '\s+', ' ').split(" ")
                $valsDict = @{}
                foreach ($cat in $CATEGORIES) {
                    if ($cat) {
                        $index = $CATEGORIES.IndexOf($cat)
                        $valsDict[$cat] = $vals[$index]
                    }
                }
                $VALUES.Add($valsDict)
                break
            }
        }
    }

    return $VALUES
}

function parse_mpstat {
    param (
        [array] $content
    )

    $LINE_MATCHES = @{"CATEGORY" = ".* +CPU +\%";
                      "VALUES" = ".* (\d+\.\d+)"}

    $VALUES = New-Object System.Collections.Generic.List[System.Object]
    $CATEGORIES = @()
    $Date = $null

    foreach ($line in $content) {
        $lineType = ""
        foreach ($key in $LINE_MATCHES.Keys) {
            if ($line -match $LINE_MATCHES[$key]) {
                $lineType = $key
                break
            }
        }
        switch ($lineType) {
            "" {
                # Write-Host "Warning: Line does not match anything"
                break
            }
            "CATEGORY" {
                $CATEGORIES = ($line -replace '\s+', ' ').split(" ")
                $Date = $CATEGORIES[0].Trim("[]")
                $CATEGORIES = $CATEGORIES | Select -Last ($CATEGORIES.Count - 2) | ForEach-Object {$_.Trim('%')}
                break
            }
            "VALUES" {
                $vals = ($line -replace '\s+', ' ').split(" ")
                $vals = $vals | Select -Last ($vals.Count - 2)
                $valsDict = @{}
                foreach ($cat in $CATEGORIES) {
                    if ($cat) {
                        $index = $CATEGORIES.IndexOf($cat)
                        $valsDict[$cat] = $vals[$index]
                    }
                }
                $valsDict["DATE"] = $Date
                $VALUES.Add($valsDict)
                break
            }
        }
    }

    return $VALUES
}

function parse_sar {
    param (
        [array] $content
    )

    $LINE_MATCHES = @{"CATEGORY" = ".* +IFACE +";
                      "VALUES" = ".* (\d+\.\d+)"}

    $VALUES = New-Object System.Collections.Generic.List[System.Object]
    $CATEGORIES = @()
    $Date = $null

    foreach ($line in $content) {
        $lineType = ""
        foreach ($key in $LINE_MATCHES.Keys) {
            if ($line -match $LINE_MATCHES[$key]) {
                $lineType = $key
                break
            }
        }
        switch ($lineType) {
            "" {
                #Write-Host "Warning: Line does not match anything"
                break
            }
            "CATEGORY" {
                $CATEGORIES = ($line -replace '\s+', ' ').split(" ")
                $Date = $CATEGORIES[0].Trim("[]")
                $CATEGORIES = $CATEGORIES | Select -Last ($CATEGORIES.Count - 2)
                break
            }
            "VALUES" {
                $vals = ($line -replace '\s+', ' ').split(" ")
                $vals = $vals | Select -Last ($vals.Count - 2)
                $valsDict = @{}
                foreach ($cat in $CATEGORIES) {
                    if ($cat) {
                        $index = $CATEGORIES.IndexOf($cat)
                        $valsDict[$cat] = $vals[$index]
                    }
                }
                $valsDict["DATE"] = $Date
                $VALUES.Add($valsDict)
                break
            }
        }
    }

    return $VALUES
}

function parse_sysbench {
    param (
        [array] $content
    )

    $LINE_MATCHES = @{"VALUES" = ".* +reads:.* +writes:"}

    $VALUES = New-Object System.Collections.Generic.List[System.Object]

    foreach ($line in $content) {
        $lineType = ""
        foreach ($key in $LINE_MATCHES.Keys) {
            if ($line -match $LINE_MATCHES[$key]) {
                $lineType = $key
                break
            }
        }
        switch ($lineType) {
            "" {
                break
            }
            "VALUES" {
                $vals = ($line -replace '\s+', ' ').split(" ")
                $valsDict = @{}
                # Date
                $date = $vals[0].Trim("[]")
                $valsDict["DATE"] = $date
                # Reads value
                $cat = $vals[4].Trim(" :")
                $readsVal = $vals[5].Trim(" ")
                $valsDict[$cat] = $readsVal
                # Writes value
                $cat = $vals[7].Trim(" :")
                $readsVal = $vals[8].Trim(" ")
                $valsDict[$cat] = $readsVal
                # Fsyncs value
                $cat = $vals[10].Trim(" :")
                $readsVal = $vals[11].Trim(" ")
                $valsDict[$cat] = $readsVal
                # Latency value
                $cat = $vals[12].Trim(" :")
                $readsVal = $vals[14].Trim(" ")
                $valsDict[$cat] = $readsVal

                $VALUES.Add($valsDict)
                break
            }
        }
    }

    return $VALUES
}

function parse_iostat {
    param (
        [array] $content
    )

    $LINE_MATCHES = @{"DATE" = "\d+-\d+-\d+T";
                      "CATEGORY" = "Device";
                      "VALUES" = "[a-z]+.*\d+ +\d+\.\d+"}

    $VALUES = New-Object System.Collections.Generic.List[System.Object]
    $CATEGORIES = @()
    $Date = $null

    foreach ($line in $content) {
        $lineType = ""

        foreach ($key in $LINE_MATCHES.Keys) {
            if ($line -match $LINE_MATCHES[$key]) {
                $lineType = $key
                break
            }
        }
        switch ($lineType) {
            "DATE" {
                $Date = $line
                $Date = $Date.Split("T")[0]
                break
            }
            "CATEGORY" {
                $CATEGORIES = ($line -replace '\s+', ' ').split(" ")
                $CATEGORIES = $CATEGORIES | ForEach-Object {$_.Trim(":. ")}
                break
            }
            "VALUES" {
                $vals = ($line -replace '\s+', ' ').split(" ")
                $valsDict = @{}
                foreach ($cat in $CATEGORIES) {
                    if ($cat) {
                        $index = $CATEGORIES.IndexOf($cat)
                        $valsDict[$cat] = $vals[$index]
                    }
                }
                $valsDict["DATE"] = $Date
                $VALUES.Add($valsDict)
                break
            }
        }
    }

    return $VALUES
}

function main {

    $content = Get-Content -Path $LogPath
    $parsedLog = $null

    switch($LogType) {
        "vmstat" {
            $parsedLog = parse_vmstat -content $content
            break
        }
        "iostat" {
            $parsedLog = parse_iostat -content $content
            break
        }
        "mpstat" {
            $parsedLog = parse_mpstat -content $content
            break
        }
        "sysbench" {
            $parsedLog = parse_sysbench -content $content
            break
        }
        "sar" {
            $parsedLog = parse_sar -content $content
            break
        }
    }

    return $parsedLog
}

main