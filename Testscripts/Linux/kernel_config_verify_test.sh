#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

. utils.sh || {
    echo "unable to source utils.sh!"
    exit 0
}

#
# Source constants file and initialize most common variables
#
UtilsInit

# kernel master config file
declare MasterConfigFile="$LIS_HOME/master.config"
declare ImageConfigFile="$LIS_HOME/image.config"

# kernel config file diff
declare ConfigDiffFile="$LIS_HOME/config.diff"

# To extract the image config file
Extract_image_config()
{
	# Check config.gz exists at /proc
	if [ -f "/proc/config.gz" ]; then
		LogMsg "the image /proc/config.gz is present"
		cp /proc/config.gz .
		gunzip -k config.gz
		cp config $ImageConfigFile
	else
		LogMsg "Error: Image config.gz file is missing or not a regular file!"
	fi

}


# To compare the master config and image config files
Compare_Kernel_Config()
{
	diff $MasterConfigFile $ImageConfigFile > $ConfigDiffFile
	return $?
}

#######################################################################
#
# Main script body
#
#######################################################################
Extract_image_config

# Check the master and image config file download is present
if [ -f "$MasterConfigFile" ]; then
	. "$MasterConfigFile"
else
	LogMsg "Error: Master config file $MasterConfigFile missing or not a regular file. Cannot source it!"
	SetTestStateAborted
	UpdateSummary "Error: Master config file $MasterConfigFile missing or not a regular file. Cannot source it!"
	return 3
fi

if [ -f "$ImageConfigFile" ]; then
	. "$ImageConfigFile"
else
	LogMsg "Error: kernel Image config file $ImageConfigFile missing or not a regular file. Cannot source it!"
	SetTestStateAborted
	UpdateSummary "Error: kernel Image config file $ImageConfigFile missing or not a regular file. Cannot source it!"
	return 3
fi

Compare_Kernel_Config
if [ 0 -eq $? ]; then
    LogMsg "Master and image config files are similar: KERNEL_CONFIG_EQUAL"
    SetTestStateCompleted
else
    LogMsg "Master and image config files are different: KERNEL_CONFIG_DIFF"
    SetTestStateFailed
fi

