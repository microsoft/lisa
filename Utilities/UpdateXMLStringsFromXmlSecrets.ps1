##############################################################################################
# UpdateXMLs.ps1
# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.
# Description : 
# Operations :
#              
## Author : lisasupport@microsoft.com
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
            Write-Host "$ReplaceString replaced in $($file.FullName)"
        }
    }
}