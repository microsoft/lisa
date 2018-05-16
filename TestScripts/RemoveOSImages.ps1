

import-module .\tools\AzureSDK\Azure.psd1  

$images = Get-AzureVMImage
$i=0

foreach ( $t in $images )
{
$OSImage = $t.ImageName
if ($OSImage -imatch 'ICA')
    {
    Write-Host "Removing $OSImage.."
    Remove-AzureVMImage -ImageName $OSImage -DeleteVHD
    }

}
