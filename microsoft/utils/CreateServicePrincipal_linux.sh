#!/bin/bash
# This script will create Azure Active Directory application, and Service Principal that can access Azure resources
# It will return clientID, tenantID, client secret
# NOTE: this version is for Linux users

printf "Starting steps of creating service principal...\n"
read -rp "Enter subscription Id: " subscriptionId

az login && az account set --subscription "$subscriptionId" && echo "Successfully login with subscription $subscriptionId"

defaultIdentifier="LISA"$(uuidgen)
identifier="1"
spacePattern=" |'"

while [ ${#identifier} -gt 0 ] && [ ${#identifier} -lt 8 ] || [[ $identifier =~ $spacePattern ]]
do
    printf "Please input identifier for your Service Principal with\n(1) MINIMUM length of 8\n(2) NO space\n"
    read -rp "Identifier name[press Enter to use default identifier $defaultIdentifier]: " identifier
done

if [[ -z "${identifier// }" ]]
then
    identifier=$defaultIdentifier
fi
echo "Use $identifier as identifier..."

role="Contributor"
echo "What kind of privileges do you want to assign to the Service Principal?"
echo "1) Contributor (Default)"
echo "2) Owner"
read -rp "Please choose by entering 1 or 2: " roleNum

if [ "$roleNum" == "2" ]
then
    role="Owner"
fi

echo "Creating service principal with identifier $identifier for role $role in subscription $subscriptionId..."
az ad sp create-for-rbac --role $role -n "$identifier" --scopes /subscriptions/"$subscriptionId"