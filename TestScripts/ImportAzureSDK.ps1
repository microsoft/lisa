################################################################# ImportAzureSDK.ps1
#
# Description: This script imports AzureSDK module into powershell.
#
# Author: Vikram Gurav <v-vigura@microsoft.com>
################################################################

# Note: The module can only be imported once into powershell.
#       If you import it a second time, the Hyper-V library function
#       calls fail.
#

$sts = get-module | select-string -pattern azure -quiet

if (! $sts)
{
	import-module .\tools\AzureSDK\Azure.psd1
    
}

################################################################