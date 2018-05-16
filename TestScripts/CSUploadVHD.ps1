#################################################################
# csuploadVHD.ps1
#
# Description: This script uploads VHD to the cloud at specified path.
#
# Author: Vikram Gurav <v-vigura@microsoft.com>
################################################################

param([string] $Destination, [string] $LiteralPath, [string] $Label)

if ($Destination-eq $null -or $Destination.Length -eq 0)
{
    "Error: Destination is null"
    return $False
}

if ($LiteralPath -eq $null -or $LiteralPath.Length -eq 0)
{
    "Error: LiteralPath is null"
    return $False
}

if ($Label -eq $null -or $Label.Length -eq 0)
{
    "Error: Label is null"
    return $False
}
################################################################

.\tools\CsUpload\csupload.exe Add-DurableImage -Destination $Destination -Label $Label -LiteralPath $LiteralPath -OS Linux

if($?)
{
	"VHD uploaded successfully to cloud.."
}
else
{
	"Error in uploading a VHD.."
	Break;
}
################################################################