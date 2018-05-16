

#import-module .\tools\AzureSDK\Azure.psd1  

$images = Get-AzureVMImage
$i=0

foreach ( $t in $images )
{
if ($t.Label -imatch "ICA")
    {
    Write-Host "$($t.Label)"
    Write-Host "$($t.ImageName)"
    Write-Host
    }

    

}
