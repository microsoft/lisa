#################################################################
# csuploadSetConnection.ps1
#
# Description: This script sets the connection of csupload application to the cloud, So that VHD can be uploaded.
# This script uses tool named csupload.exe kept in \ica\CsUpload directory. This tool works only with 64 nit machine
# 
# Author: Vikram Gurav <v-vigura@microsoft.com>
################################################################

param([string] $subscription)

if ($subscription -eq $null -or $subscription.Length -eq 0)
{
    "Error: Subscription is null"
    return $False
}
################################################################

.\tools\CsUpload\csupload Set-Connection $subscription

if($?)
{
	"Csupload connection set successfully.."
}
else
{
	"Error in setting up Csupload connection.."
	Break;
}


################################################################