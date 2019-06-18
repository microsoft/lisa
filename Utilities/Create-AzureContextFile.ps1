# Remove the saved contexts from current PS session to avoid unauthorized export of saved contexts.
Write-Host "Deleting the current Azure authorization information, if any."
Clear-AzureRmContext -Verbose

Write-Host "Please complete the login at next step."
Connect-AzureRmAccount

Save-AzureRmContext -Path .\AzureSessionContext.json
Write-Host "Context file saved: .\AzureSessionContext.json"
Write-Host "--------------------------------------------------------------------------------------------"
Write-Host "DO NOT SHARE THIS FILE WITH ANYONE TO AVOID UNAUTHORIZED ACCESS TO YOUR AZURE SUBSCRIPTIONS."
Write-Host "--------------------------------------------------------------------------------------------"

Clear-AzureRmContext -Verbose