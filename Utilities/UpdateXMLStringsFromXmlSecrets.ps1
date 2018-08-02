##############################################################################################
# UpdateXMLStringFromXmlSecrets.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    This file updates REPLACEBLE STRINGS in XML files under .\XML\TestCases.

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE


#>
###############################################################################################
param(
    [string]$XmlSecretsFilePath= ""
)
$TestXMLs = Get-ChildItem -Path ".\XML\TestCases\*.xml"
$XmlSecrets = [xml](Get-Content $XmlSecretsFilePath)
foreach ($file in $TestXMLs)
{
    $CurrentXMLText = Get-Content -Path $file.FullName
    foreach ($Replace in $XmlSecrets.secrets.ReplaceTestXMLStrings.Replace)
    {
        $ReplaceString = $Replace.Split("=")[0]
        $ReplaceWith = $Replace.Split("=")[1]
        if ($CurrentXMLText -imatch $ReplaceString)
        {
            $content = [System.IO.File]::ReadAllText($file.FullName).Replace($ReplaceString,$ReplaceWith)
            [System.IO.File]::WriteAllText($file.FullName, $content)
            LogMsg "$ReplaceString replaced in $($file.FullName)"
        }
    }
}