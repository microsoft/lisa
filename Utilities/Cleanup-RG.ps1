# Variables
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
        This is a script that performs a cleanup on Resource Groups from Lisav2 and Lisav3 automation using rest api.
#>

param(
    [String] $TenantId,
    [String] $ClientId,
    [String] $ClientSecret,
    [String] $SubscriptionId,
    [String] $Resource = "https://management.core.windows.net/",
    [String] $APIVersion = "2020-06-01",
    [int] $CleanupAgeInDays = 1
)

if ($CleanupAgeInDays -lt 1) {
    Write-Host "Please specify a vaild CleanupAgeInDays, current value is less 1 day."
    return
}
# Get A Token
$RequestAccessTokenUri = "https://login.microsoftonline.com/$TenantId/oauth2/token"
$body = "grant_type=client_credentials&client_id=$ClientId&client_secret=$ClientSecret&resource=$Resource"
$Token = Invoke-RestMethod -Method Post -Uri $RequestAccessTokenUri -Body $body -ContentType 'application/x-www-form-urlencoded'
if ($?) {
    Write-Host "******************************************************************************************************************************"
    Write-Host "Get a token successfully for subscription $SubscriptionId." -ForegroundColor Green
    Write-Host "Start to cleanup Resource Groups for subscription $SubscriptionId."
} else {
    Write-Host "Fail to get a token." -ForegroundColor Red
    return
}

# Get Azure Resource Groups
$ResourceGroupApiUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourcegroups?api-version=${APIVersion}&%24expand=createdTime,changedTime"
$Headers = @{}
$Headers.Add("Authorization","$($Token.token_type) "+ " " + "$($Token.access_token)")
$ResourceGroups = Invoke-RestMethod -Method Get -Uri $ResourceGroupApiUri -Headers $Headers
$currentTimeStamp = get-date

foreach($value in $ResourceGroups.value) { 
    if(($value.name.Contains("lisa_") -or $value.name.Contains("LISAv2")) -and !$value.name.Contains("LISAv2-storage") -and !$value.name.Contains("LISAv2DependenciesRG") -and !$value.name.Contains("lisa_shared_resource") -and !$value.name.Contains("LISAv2-Deploy1VM")) {
          $rgTimeStamp = [DateTime]($value.changedTime)
          if(($currentTimeStamp - $rgTimeStamp).Days -ge $CleanupAgeInDays) {
                $rg = $value.name
                Write-Host "=============================================================================================================================="
                Write-Host "$rg will be deleted, latest updated time is $($value.changedTime)"
                $DeleteApiUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourcegroups/${rg}?api-version=${APIVersion}"
                Invoke-RestMethod -Method Delete -Uri $DeleteApiUri -Headers $Headers
                if ($?) {
                    Write-Host "Delete $rg successfully." -ForegroundColor Green
                } else {
                    Write-Host "Fail to delete $rg. Please delete it manually." -ForegroundColor Red
                }
          }
    }
}
Write-Host "End to cleanup Resource Groups for subscription $SubscriptionId."
Write-Host "******************************************************************************************************************************"
