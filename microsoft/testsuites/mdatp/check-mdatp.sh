#! /bin/sh

# check the following folders for printable files, print them
FOUND_DEFENDER=1
MDATP_OPT_DIR='/etc/opt/microsoft/mdatp'
MDATP_EXTENSION_DIR='/var/lib/waagent/Microsoft.Azure.AzureDefenderForServers.MDE.Linux'
MDATP_LOG_DIR='/var/log/microsoft/mdatp'

# check for mdatp installation
if [ -e $MDATP_OPT_DIR ]; then
    # dump all the filenames to console
    FOUND_DEFENDER=0
    # find regular files, skip printing them if they are binary
    sudo find "$MDATP_OPT_DIR" -type f -exec file '{}' ';' -exec grep -Iq . '{}' ';' -exec cat '{}' ';'
fi
# check for azure extension install dir
if [  -e $MDATP_EXTENSION_DIR ]; then
    FOUND_DEFENDER=0
    sudo find "$MDATP_EXTENSION_DIR" -type f -exec file '{}' ';' -exec grep -Iq . '{}' ';'  -exec cat '{}' ';'
fi
# check for install or runtime logs
if [  -e $MDATP_LOG_DIR ]; then
    FOUND_DEFENDER=0
    sudo find "$MDATP_LOG_DIR" -type f -exec file '{}' ';' -exec grep -Iq . '{}' ';'  -exec cat '{}' ';'
fi


exit $FOUND_DEFENDER