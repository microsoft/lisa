#!/usr/bin/env bash
# create-service-principal.sh [--subscription=${uuid}] [--id="<name>"] [--role=Contributor | Owner] --pathname=${pathname}
# The default subscription is the one you're currently logged into.
# The default id is ${USER}-penguinator-sp.
# The default role is Owner.

# http://redsymbol.net/articles/unofficial-bash-strict-mode/
set -Eeuo pipefail
# print arguments to stderr and exit with error status.
err() { >&2 echo $0: $@; exit 1; }

# return the default id, e.g. `mcarifio-penguinator-sp`
# default.id() { printf LISA$(uuidgen); }
default.id() { printf "%s-penguinator-sp" ${USER}; }

# return the default role. Modify this function to default to Owner.
# default.role() { printf "Contributor"; }
default.role() { printf "Owner"; }

# Are you logged in to azure?
az account show &> /dev/null || err "$0: you're not logged in. Please do so first."

# What subscription are you logged into? --out tsv loses the string quotes.
current_subscription="$(az account show --query 'id' --out tsv)"


# Parse the command line. Never elegant in bash.
for _token in "$@"; do
    case "${_token}" in
        --*=* )
            # flag with a value
            _keyword=${_token%=*}
            _keyword=${_keyword#--}
            # Brittle. --author=mcarifio would be accepted.
            printf -v ${_keyword} '%s' "${_token#*=}"
            ;;
        --* )
            _keyword=${_token#--}
            if [[ help -eq "${_keyword}" ]] ; then
                err "$0 [--subscription=\${uuid}] [--id="<name>"] [--role=Contributor|Owner]"
            fi
            err "--${_keyword} unexpected switch"
            ;;
        * )            
            err "${_token} unexpected argument"
    esac        
done

# subscription
subscription=${subscription:-"${current_subscription}"}

# id
id=${id:-$(default.id)}
# I don't check the length.
# [[ ${#id} -ge 8 ]] && err "'${id}' is longer than 7 characters."
[[ "${id}" =~ [[:space:]] ]] && err "'${id}' contains whitespace."


# role
role=${role:-$(default.role)}

# pathname
ext=azure.ServicePrincipal.Password.json
pathname=${pathname:-/tmp/$(basename $0)-$$.${ext}}

if [[ "${subscription}" != "${current_subscription}" ]] ; then
    # set the subscription for id
    az account set --subscription "${subscription}"
    # set it back upon exit
    trap EXIT "az account set --subscription ${current_subscription}"
fi

>&2 printf "Creating service principal '${id}' with role '${role}' in subscription '${subscription}'..."
# https://learn.microsoft.com/en-us/cli/azure/ad/sp?view=azure-cli-latest
if az ad sp create-for-rbac --role ${role} -n "${id}" --scopes /subscriptions/${subscription} > ${pathname} ; then
    # [[ -r "${pathname}" ]] && >&2 echo "password written to '${pathname}'"
    >&2 echo "succeeded, output ${pathname}"
    sp=$(jq -r .appId ${pathname})
    az ad sp show --id "${sp}"
else
    >&2 echo "failed."
    exit 1
fi


