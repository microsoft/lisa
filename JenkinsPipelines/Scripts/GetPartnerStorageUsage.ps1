##############################################################################################
# GetPartnerStorageUsage.ps1
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

Param
( 
    $JenkinsUser,
    $RemoteReceivedFolder="J:\ReceivedFiles",
    $htmlFilePath,
    $textFilePath,
    $cleanupFilesPath 
)

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global }
$folderToQuery = "$RemoteReceivedFolder\$JenkinsUser"

$htmlHeader = '
<style type="text/css">
.tg  {border-collapse:collapse;border-spacing:0;border-color:#999;}
.tg td{font-family:Arial, sans-serif;font-size:14px;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#444;background-color:#F7FDFA;}
.tg th{font-family:Arial, sans-serif;font-size:14px;font-weight:normal;padding:10px 5px;border-style:solid;border-width:1px;overflow:hidden;word-break:normal;border-color:#999;color:#fff;background-color:#26ADE4;}
.tg .tg-baqh{text-align:center;vertical-align:top}
.tg .tg-90qj{font-weight:bold;background-color:#26ade4;color:#ffffff;text-align:center;vertical-align:top}
.tg .tg-lqy6{text-align:right;vertical-align:top}
.tg .tg-0ol0{font-weight:bold;background-color:#26ade4;color:#ffffff;text-align:right;vertical-align:top}
.tg .tg-yw4l{vertical-align:top}
.tg .tg-9hbo{font-weight:bold;vertical-align:top}
.tg .tg-l2oz{font-weight:bold;text-align:right;vertical-align:top}
.tg .tg-2nui{font-weight:bold;background-color:#ffffc7;text-align:right;vertical-align:top}
</style>
<table class="tg">
  <tr>
    <th class="tg-90qj">SR</th>
    <th class="tg-90qj">File Name</th>
    <th class="tg-90qj">Uploaded Date</th>
    <th class="tg-0ol0">Size</th>
  </tr>
'

$htmlRow='
<tr>
<td class="tg-baqh">CURRENT_SERIAL</td>
<td class="tg-yw4l">CURRENT_FILENAME</td>
<td class="tg-lqy6">CURRENT_DATE</td>
<td class="tg-lqy6">CURRENT_SIZE</td>
</tr>
'
$htmlFooter='
<tr>
<td class="tg-9hbo"></td>
<td class="tg-9hbo"></td>
<td class="tg-l2oz">Total Usage</td>
<td class="tg-2nui">TOTAL_USAGE</td>
</tr>
</table>
'

try 
{
    $currentFiles = Get-ChildItem -Path $folderToQuery -Recurse -Verbose
    $SR = 1
    $htmlData = ""
    
    function GetFileObject()
    {
        $object = New-Object -TypeName PSObject
        $object | Add-Member -MemberType NoteProperty -Name SR -Value $null
        $object | Add-Member -MemberType NoteProperty -Name FileName -Value $null
        $object | Add-Member -MemberType NoteProperty -Name LastWriteTime -Value $null
        $object | Add-Member -MemberType NoteProperty -Name Size -Value $null
        return $object
    }
    
    $htmlData += $htmlHeader
    $totalSize = 0
    $allFileObjects = @()
    $cleanupFileList = "FileName="
    foreach ($file in $currentFiles)
    {
        $currentHTMLRow = $htmlRow
        $currentHTMLRow = $currentHTMLRow.Replace("CURRENT_SERIAL","$SR")
        $currentHTMLRow = $currentHTMLRow.Replace("CURRENT_FILENAME","$($file.Name)")
        $cleanupFileList += "$($file.Name),"
        $currentHTMLRow = $currentHTMLRow.Replace("CURRENT_DATE","$($file.LastWriteTime)")
        $currentFileSize = [math]::Round($($file.Length / 1024 / 1024 / 1024 ),3)
        $currentHTMLRow = $currentHTMLRow.Replace("CURRENT_SIZE","$currentFileSize GB")
        $totalSize += $file.Length
        $htmlData += $currentHTMLRow
        $fileObject = GetFileObject
        $fileObject.SR = $SR
        $fileObject.FileName = $($file.Name)
        $fileObject.LastWriteTime = $file.LastWriteTime
        $fileObject.Size = "$currentFileSize GB"
        $allFileObjects += $fileObject
        $SR += 1
    }
    if ( $currentFiles.Count -gt 0)
    {
        $totalSizeInGB = [math]::Round(($totalSize / 1024 / 1024 / 1024),3)
    
        $currentHtmlFooter = $htmlFooter
        $currentHtmlFooter = $currentHtmlFooter.Replace("TOTAL_USAGE","$totalSizeInGB GB")
        $htmlData += $currentHtmlFooter
        Set-Content -Value $htmlData -Path $htmlFilePath -Force -Verbose
        Remove-Item -Path $textFilePath -Force -Verbose
        $allFileObjects | Out-File -FilePath $textFilePath -Force -Verbose -NoClobber
        Add-Content -Value "--------------------------------------------------------" -Path $textFilePath
        Add-Content -Value "                                       Total : $totalSizeInGB GB" -Path $textFilePath
        $cleanupFileList = $cleanupFileList.TrimEnd(",")    
        if ($currentFiles.Count -gt 2)
        {
            $cleanupFileList = $cleanupFileList.Replace("FileName=","FileName=Delete All Files,")
        }
        Set-Content -Value $cleanupFileList -Path $cleanupFilesPath -Force -Verbose
    }
    else 
    {
        $currentHtmlFooter = $htmlFooter
        $currentHtmlFooter = $currentHtmlFooter.Replace("TOTAL_USAGE","0 GB")
        $htmlData += $currentHtmlFooter
        Set-Content -Value $htmlData -Path $htmlFilePath -Force -Verbose
        Remove-Item -Path $textFilePath -Force -Verbose
        $allFileObjects | Out-File -FilePath $textFilePath -Force -Verbose -NoClobber
        Add-Content -Value "--------------------------------------------------------" -Path $textFilePath
        Add-Content -Value "                                       Total : 0 GB" -Path $textFilePath
        Set-Content -Value "" -Path $cleanupFilesPath -Force -Verbose   
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