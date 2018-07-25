##############################################################################################
# DeletePartnerFiles.ps1
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
    $JenkinsUser,
    $RemoteReceivedFolder = "J:\ReceivedFiles",
    $fileNames
)
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }

try
{
    $folderToQuery = "$RemoteReceivedFolder\$JenkinsUser"
    if ($fileNames)
    {
        if (  ($fileNames -imatch "Delete All Files" ) )
        {
            $allFiles = Get-ChildItem "$folderToQuery"
            foreach ( $file in $allFiles.Name)
            {
                LogMsg "Removing $file..." -NoNewline
                $out = Remove-Item -Path "$folderToQuery\$file" -Force
                if ($?)
                {
                    LogMsg " SUCCESS"
                }
                else 
                {
                    LogMsg " Error"    
                }            
            }
        }
        else 
        {
            foreach ($file in $fileNames.split(","))
            {
                if ( ( Test-Path -Path "$folderToQuery\$file"))
                {
                    LogMsg "Removing $file..." -NoNewline
                    $out = Remove-Item -Path "$folderToQuery\$file" -Force
                    if ($?)
                    {
                        LogMsg " SUCCESS"
                    }
                    else 
                    {
                        LogMsg " Error"    
                    }
                }
                else 
                {
                    LogMsg "$folderToQuery\$file does not exeists."
                }
            }        
        }
    }
    else 
    {
        LogMsg "Please select at leat one file."    
    }
    $ExitCode = 0   
}
catch 
{
    $ExitCode = 1
    ThrowExcpetion($_)
}
finally
{
    LogMsg "Exiting with ExitCode = $ExitCode"
    exit $ExitCode 
}