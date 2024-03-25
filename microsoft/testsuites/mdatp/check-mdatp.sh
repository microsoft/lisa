#! /bin/bash

function is_text {
    # run 'file' and check for ASCII or UTF-8 encoded files
    IS_ASCII=$( file "$1" | grep 'ASCII' );
    IS_UTF=$( file "$1" | grep 'UTF-8' );
    IS_JSON=$( file "$1" | grep 'JSON' );

    # if the files have no text or json content, return false
    if [[ -z "$IS_ASCII" ]] && [[ -z "$IS_UTF" ]] && [[ -z "$IS_JSON" ]]; then 
        return 1; 
    fi
    return 0; 
}

FOUND_DEFENDER=1
if ! shopt -s globstar; then
    echo "Warning, could not set globstar option! File results might be truncated."
fi

# check for mdatp installation
if [[ -e /etc/opt/microsoft/mdatp/ ]]; then
    # dump all the filenames to console
    FOUND_DEFENDER=0
    for file in /etc/opt/microsoft/mdatp/** ; do
        echo "$file ________________________________"
        # if the file is printable, print it
        if is_text "$file"; then
            cat "$file"
        else
            file "$file"
        fi
    done
fi

if [[  -e '/var/lib/waagent/Microsoft.Azure.AzureDefenderForServers.MDE.Linux' ]]; then
    FOUND_DEFENDER=0
    for file in /var/lib/waagent/Microsoft.Azure.AzureDefenderForServers.MDE.Linux/** ; do
        echo "$file ________________________________"
        # if the file is printable, print it
        if is_text "$file"; then
            cat "$file"
        else
            file "$file"
        fi
    done
fi

exit $FOUND_DEFENDER