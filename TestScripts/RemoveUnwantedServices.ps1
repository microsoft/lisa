Import-Module .\tools\AzureSDK\Azure.psd1

$ExistingServices = Get-AzureService

foreach ($service in $ExistingServices)
    {

    if ((($service.ServiceName -imatch "ICA") -and ($service.ServiceName -imatch "2013")))# -and !($service.ServiceName -imatch "19"))
        {
        Write-Host "Removing $($service.ServiceName).."
        sleep 10
        Remove-AzureService -ServiceName $service.ServiceName -Force -ErrorAction Continue
        }

    }
