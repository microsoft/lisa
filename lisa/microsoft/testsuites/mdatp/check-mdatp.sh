#! /bin/sh

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# check the following folders for printable files, print them
# checks Azure Extension directories using globs, since they're not 
# well-known.

# Returns nonzero value on detection of any defender info.
# Return value are ordered by seriousness of the issue:
# Lower value is bad
# Highest value is worst.

# Publishers: Re-run and remediate until you get a 0 return code.

EXIT_CODE=0
# if any mdatp install in /etc/opt is found
EXIT_MDATP_AGENT_INSTALLED=251
# if mdatp az extension is installed
EXIT_MDE_INSTALLED=252
# if any log dirs are found
EXIT_MDATP_LOGS_FOUND=253
# if an installation log is found
EXIT_MDATP_INSTALL_LOGS_FOUND=254
# if an onboarding blob is found
EXIT_ONBOARD_INFO_FOUND=255
MDATP_OPT_DIR='/etc/opt/microsoft/mdatp'
MDATP_LOG_DIR='/var/log/microsoft/mdatp'
ERROR_MSG_HEADER="----------------------------------------------------------------------"

find_printable_files () {
    found_dir="$1"
    sudo find "$found_dir" -type f -exec file '{}' ';' -exec grep -Iq . '{}' ';' -exec head -c 1024 '{}' ';'
}

check_unexpected_file () {
    surprise_file="$1"
    echo "Found unexpected regular file: $surprise_file" >&2
    # see what it is, print if it's printable
    file "$surprise_file"; grep -Iq . "$surprise_file" && cat "$surprise_file"
}

# check for MDE extension installation, folder is version labeled, so use a shell glob
for mde_dir in /var/lib/waagent/Microsoft.Azure.AzureDefenderForServers.MDE.Linux* ; do
    # for all the versioned folders we find...
    if [ -e "$mde_dir" ]; then
        EXIT_CODE=$EXIT_MDE_INSTALLED
        if [ -d "$mde_dir" ]; then
            # find regular files, skip printing them if they are binary
            find_printable_files "$mde_dir"
        else
            # not expecting to find a regular file instead of a dir, but...
            check_unexpected_file "$mde_dir"
        fi
    fi
done

# check for ARM log files
for log_dir in /var/log/azure/Microsoft.Azure.AzureDefenderForServers.MDE.Linux* ; do
    # for all the versioned folders we find...
    if [ -e "$log_dir" ]; then
        EXIT_CODE=$EXIT_MDATP_LOGS_FOUND
        echo "checking $log_dir..."
        if [ -d "$log_dir" ]; then
            find_printable_files "$log_dir"
        else
            # not expecting to find a regular file in /var/log/azure, but...
            check_unexpected_file "$log_dir"
        fi
    fi
done

# check for ARC logs
for log_dir in /var/lib/GuestConfig/extension_logs/Microsoft.Azure.AzureDefenderForServers.MDE.Linux* ; do
    # for all the versioned folders we find...
    if [ -e "$log_dir" ]; then
        EXIT_CODE=$EXIT_MDATP_LOGS_FOUND
        echo "checking $log_dir..."
        if [ -d "$log_dir" ]; then
            find_printable_files "$log_dir"
        else
            check_unexpected_file "$log_dir"
        fi
    fi
done

# check for mde agent install in /etc/opt
if [  -e "$MDATP_OPT_DIR" ]; then
    EXIT_CODE=$EXIT_MDATP_AGENT_INSTALLED
    find_printable_files "$MDATP_OPT_DIR"
fi

# check for install or runtime logs in /var/log
if [  -e "$MDATP_LOG_DIR" ]; then
    EXIT_CODE=$EXIT_MDATP_LOGS_FOUND
    find_printable_files "$MDATP_LOG_DIR"
fi

# special log line for install logs
if [ -f "$MDATP_LOG_DIR/install.log" ]; then
    echo "$ERROR_MSG_HEADER" >&2
    echo "ERROR: mdatp install logs are present in this image!" >&2
    echo "Publishers should remove this data before publishing public images." >&2
    EXIT_CODE=$EXIT_MDATP_INSTALL_LOGS_FOUND
fi

# special log line for mdatp_onboard.json
if [ -f "$MDATP_OPT_DIR/mdatp_onboard.json" ]; then
    echo "$ERROR_MSG_HEADER" >&2
    echo "ERROR: mdatp onboarding info is present in this image!" >&2
    echo "Publishers should remove this data before publishing public images." >&2
    EXIT_CODE=$EXIT_ONBOARD_INFO_FOUND
fi

# special log line if mdatp installed and reports it is onboarded
MDATP_ORG_ID=$(\
    command -v mdatp \
    && mdatp health \
    | grep --fixed-strings 'org_id:' \
    | cut -f 2 -d ':' \
    | tr -d '[:blank:][:punct:]' \
)
if [ -n "$MDATP_ORG_ID" ]; then
    echo "$ERROR_MSG_HEADER" >&2
    echo "ERROR: mdatp is installed and reports this device is onboarded:" >&2
    sudo mdatp health >&2
    EXIT_CODE=$EXIT_ONBOARD_INFO_FOUND
fi

# returns nonzero value if defender info is found
exit $EXIT_CODE