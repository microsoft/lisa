##############################################################################################
# TestHelpers.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation.
	This module defines a set of helper functions.

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Function New-TestID()
{
	return "{0}{1}" -f $(-join ((65..90) | Get-Random -Count 2 | ForEach-Object {[char]$_})), $(Get-Random -Maximum 99 -Minimum 11)
}

Function New-TimeBasedUniqueId()
{
	return Get-Date -UFormat "%Y%m%d%H%M%S"
}