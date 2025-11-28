# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# This script is to create/update a custom role and grant to Service Principal for AITL
# Debug sample: .\setup_aitl.py -r "role_name" -p "SP_Name" -s "/subscriptions/xxxxx"
# User sample:  .\setup_aitl.py

import json
import logging
import subprocess
import time
from argparse import ArgumentParser, Namespace
from typing import Any, List, Tuple

_fmt = "%(asctime)s.%(msecs)03d[%(thread)d][%(levelname)s] %(name)s %(message)s"
_datefmt = "%Y-%m-%d %H:%M:%S"


def _call_cmd(command: str) -> "subprocess.CompletedProcess[str]":
    # Run the command and capture the return code
    result = subprocess.run(
        command,
        shell=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return_code = result.returncode
    logging.debug(f"Return Code: {return_code} for cmd: {command}")
    # output = result.stdout
    # logging.info(f"Output:\n{output}") # can open for debug purpose
    return result


def _compare_str_list(str_list_1: List[str], str_list_2: List[str]) -> bool:
    return sorted(str_list_1) == sorted(str_list_2)


def _compare_role_setting(role_previous_json: str, role_current_json: str) -> bool:
    # input from az role list output, is an array: [role...]
    if not role_previous_json or not role_current_json:
        return False

    previous_roles = json.loads(role_previous_json)
    current_roles = json.loads(role_current_json)
    if len(previous_roles) != 1 or len(current_roles) != 1:
        # az role list output JSON should only have 1 role definition
        return False

    role_previous = previous_roles[0]
    role_current = current_roles[0]

    is_actions_match = _compare_str_list(
        role_previous["permissions"][0]["actions"],
        role_current["permissions"][0]["actions"],
    )
    is_dataactions_match = _compare_str_list(
        role_previous["permissions"][0]["dataActions"],
        role_current["permissions"][0]["dataActions"],
    )
    is_scopes_match = _compare_str_list(
        role_previous["assignableScopes"], role_current["assignableScopes"]
    )

    if (
        (role_previous["description"] == role_current["description"])
        and (role_previous["roleName"] == role_current["roleName"])
        and is_actions_match
        and is_dataactions_match
        and is_scopes_match
    ):
        return True
    else:
        return False


def _check_same_role_existed(exist_role_json: str, target_role_json: str) -> bool:
    # exist_role_json from az role list output, is an array: [role...]
    # target_role_json from cmdline input, format is different from exist_role_json
    if exist_role_json == "" or exist_role_json == "":
        return False

    exist_role_array = json.loads(exist_role_json)
    if len(exist_role_array) != 1:
        return False
    exist_role = exist_role_array[0]

    target_role = json.loads(target_role_json)

    is_actions_match = _compare_str_list(
        exist_role["permissions"][0]["actions"], target_role["Actions"]
    )
    is_dataactions_match = _compare_str_list(
        exist_role["permissions"][0]["dataActions"], target_role["DataActions"]
    )
    is_scopes_match = _compare_str_list(
        exist_role["assignableScopes"], target_role["AssignableScopes"]
    )

    if (
        (exist_role["description"] == target_role["Description"])
        and (exist_role["roleName"] == target_role["Name"])
        and is_actions_match
        and is_dataactions_match
        and is_scopes_match
    ):
        return True
    else:
        return False


def _wait_role_propagate(
    role_name: str, subscription_id: str, role_before_update: str = ""
) -> None:
    logging.info("In _wait_role_propagate: waiting for the role changes to propagate")

    sleep_interval = 5
    time_out = 400
    required_continuous_change_count = 5
    count = 0
    start_time = time.time()
    # check changes happened continuous multiple times to make sure cache is refreshed.
    while time.time() - start_time < time_out:
        logging.info("Checking change applied...")
        get_role_cmd_result = _call_cmd(
            f'az role definition list --name "{role_name}" --scope "{subscription_id}"'
        )
        role_after_update = get_role_cmd_result.stdout

        # for role creation completed
        if role_after_update.startswith("[]"):
            count = 0
            logging.debug("--- No role found.")
        else:
            is_same = _compare_role_setting(role_before_update, role_after_update)
            if is_same:
                # if no changes then reset count 0
                count = 0
                logging.debug("--- Role setting Not Updated.")
            else:
                count += 1
                logging.debug("--- Found changed results.")

        if count >= required_continuous_change_count:
            break
        time.sleep(sleep_interval)

    elapsed_time = time.time() - start_time
    logging.info(f"Role is propagated in {elapsed_time} sec")


def _init_arg_parser() -> Namespace:
    parser = ArgumentParser(
        description="Create/Update a custom role and grant to Service Principal"
    )
    parser.add_argument(
        "-r",
        "--role",
        default="Azure Image Testing for Linux Delegator",
        help="RoleName you want to create/update",
    )
    parser.add_argument(
        "-p",
        "--service_principal",
        default="AzureImageTestingforLinux",
        help="Service Principal Name you want to assign",
    )
    parser.add_argument(
        "-s",
        "--subscriptionId",
        default="",
        help="Subscription scope in Role assignment(default is current subscription)",
    )
    parser.add_argument(
        "-d",
        "--debug",
        dest="debug",
        action="store_true",
        help="""Set the log level output by the console to DEBUG level. By default, the
console displays logs with INFO and higher levels. The log file will
contain the DEBUG level and is not affected by this setting.
        """,
    )
    return parser.parse_args()


def _set_target_role_parameters(
    subscription_id: str, role_name: str
) -> Tuple[str, str]:
    if subscription_id == "":
        account_cmd_result = _call_cmd("az account show")
        account_info = json.loads(account_cmd_result.stdout)
        subscription_id = "/subscriptions/" + account_info["id"]
        logging.info(
            f"Input subscription_id is empty, use default one: {subscription_id}"
        )

    action_perms_list = [
        "Microsoft.Resources/subscriptions/resourceGroups/read",
        "Microsoft.Resources/subscriptions/resourceGroups/write",
        "Microsoft.Resources/subscriptions/resourceGroups/delete",
        "Microsoft.Resources/deployments/read",
        "Microsoft.Resources/deployments/write",
        "Microsoft.Resources/deployments/validate/action",
        "Microsoft.Resources/deployments/operationStatuses/read",
        "Microsoft.Compute/virtualMachines/read",
        "Microsoft.Compute/virtualMachines/write",
        "Microsoft.Compute/virtualMachines/retrieveBootDiagnosticsData/action",
        # for availability set testing
        "Microsoft.Compute/availabilitySets/write",
        # for verify GPU PCI device count should be same after stop-start
        "Microsoft.Compute/virtualMachines/start/action",
        "Microsoft.Compute/virtualMachines/restart/action",
        "Microsoft.Compute/virtualMachines/deallocate/action",
        "Microsoft.Compute/virtualMachines/powerOff/action",
        # for testing hot adding disk
        "Microsoft.Compute/disks/read",
        "Microsoft.Compute/disks/write",
        "Microsoft.Compute/disks/delete",
        "Microsoft.Compute/images/read",
        "Microsoft.Compute/images/write",
        # for testing ARM64 VHD and gallery image
        "Microsoft.Compute/galleries/images/read",
        "Microsoft.Compute/galleries/images/write",
        "Microsoft.Compute/galleries/images/delete",
        "Microsoft.Compute/galleries/images/versions/read",
        "Microsoft.Compute/galleries/images/versions/write",
        "Microsoft.Compute/galleries/images/versions/delete",
        "Microsoft.Compute/galleries/read",
        "Microsoft.Compute/galleries/write",
        # for test VM extension running
        "Microsoft.Compute/virtualMachines/extensions/read",
        "Microsoft.Compute/virtualMachines/extensions/write",
        "Microsoft.Compute/virtualMachines/extensions/delete",
        # for verify_vm_assess_patches
        "Microsoft.Compute/virtualMachines/assessPatches/action",
        # for VM resize test suite
        "Microsoft.Compute/virtualMachines/vmSizes/read",
        # For disk_support_restore_point & verify_vmsnapshot_extension
        "Microsoft.Compute/restorePointCollections/write",
        # For verify_vmsnapshot_extension
        "Microsoft.Compute/restorePointCollections/restorePoints/read",
        "Microsoft.Compute/restorePointCollections/restorePoints/write",
        "Microsoft.ManagedIdentity/userAssignedIdentities/write",
        # For verify_azsecpack
        "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action",
        "Microsoft.Network/virtualNetworks/read",
        "Microsoft.Network/virtualNetworks/write",
        "Microsoft.Network/virtualNetworks/subnets/join/action",
        "Microsoft.Network/publicIPAddresses/read",
        "Microsoft.Network/publicIPAddresses/write",
        "Microsoft.Network/publicIPAddresses/join/action",
        "Microsoft.Network/networkInterfaces/read",
        "Microsoft.Network/networkInterfaces/write",
        "Microsoft.Network/networkInterfaces/join/action",
        # for verify_dpdk_l3fwd_ntttcp_tcp to set up Azure route table
        "Microsoft.Network/routeTables/read",
        "Microsoft.Network/routeTables/write",
        # for verify_azure_file_share_nfs mount and delete
        "Microsoft.Network/privateEndpoints/write",
        "Microsoft.Network/privateLinkServices/PrivateEndpointConnectionsApproval/action",  # noqa: E501
        # for verify_serial_console write operation
        "Microsoft.SerialConsole/serialPorts/write",
        # For setting firewall rules to access Microsoft tenant VMs
        "Microsoft.Network/networkSecurityGroups/write",
        "Microsoft.Network/networkSecurityGroups/read",
        "Microsoft.Network/networkSecurityGroups/join/action",
        "Microsoft.Storage/storageAccounts/read",
        "Microsoft.Storage/storageAccounts/write",
        "Microsoft.Storage/storageAccounts/listKeys/action",
        "Microsoft.Storage/storageAccounts/blobServices/containers/delete",
        "Microsoft.Storage/storageAccounts/blobServices/containers/read",
        "Microsoft.Storage/storageAccounts/blobServices/containers/write",
        "Microsoft.Storage/storageAccounts/blobServices/generateUserDelegationKey/action",  # noqa: E501
    ]

    data_action_perms_list = [
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action",
    ]

    target_role = {
        "Description": (
            "Delegation role is to run test cases and upload logs in "
            "Azure Image Testing for Linux (AITL)."
        ),
        "IsCustom": True,
        "Name": role_name,
        "Actions": action_perms_list,
        "DataActions": data_action_perms_list,
        "AssignableScopes": [subscription_id],
    }
    target_role_json = json.dumps(target_role, indent=4)

    return subscription_id, target_role_json


def _get_service_principal_objectid(service_principal_name: str) -> Any:
    # If Service Principal not exist, raise exception
    get_service_principal_result = _call_cmd(
        (
            f'az ad sp list --display-name "{service_principal_name}" '
            " --filter \"servicePrincipalType eq 'Application'\""
        )
    )
    service_principals = json.loads(get_service_principal_result.stdout)
    if len(service_principals) == 0:
        raise SystemExit(
            f"Error: Service Principal {service_principals} not exist! "
            "You need register Resource Provider Firstly"
        )
    else:
        # different az command versions have different ObjectID keys
        if "id" in service_principals[0].keys():
            service_principal_objectid = service_principals[0]["id"]
        elif "objectId" in service_principals[0].keys():
            service_principal_objectid = service_principals[0]["objectId"]
        else:
            raise SystemExit(
                f"Error: Service Principal {service_principals} Object ID not exist! "
            )

    return service_principal_objectid


# Create or Update Role settings according to target role json
def _set_target_role(
    target_role_json: str, role_name: str, subscription_id: str
) -> None:
    with open("role.json", "w") as outfile:
        outfile.write(target_role_json)

    get_role_cmd_result = _call_cmd(
        f'az role definition list --name "{role_name}" --scope "{subscription_id}"'
    )
    exist_role = get_role_cmd_result.stdout

    if exist_role.startswith("[]"):
        # create
        logging.info(f"creating new role '{role_name}':")
        _call_cmd("az role definition create --role-definition role.json")
        _wait_role_propagate(role_name, subscription_id, "")
    else:
        # update
        logging.info(f"Try to update role '{role_name}' :")

        is_same_role = _check_same_role_existed(exist_role, target_role_json)
        if is_same_role is True:
            logging.info(
                f"Input Role '{role_name}' is same with exist one, won't update"
            )
        else:
            # only update when different.
            logging.debug(f"Updating existed role: '{role_name}' with parameters: ")
            logging.debug(target_role_json)
            _call_cmd("az role definition update --role-definition role.json")
            _wait_role_propagate(role_name, subscription_id, exist_role)


def _assign_role_to_service_principal(
    role_name: str,
    service_principal_name: str,
    service_principal_objectid: str,
    subscription_id: str,
) -> None:
    logging.info(
        f"Assign role '{role_name}' to ServicePrincipal {service_principal_name} "
        f"with ID: {service_principal_objectid}"
    )

    max_tries = 10
    for i in range(max_tries):
        try:
            _call_cmd(
                f'az role assignment create --role "{role_name}" --assignee-object-id '
                f' "{service_principal_objectid}" --scope "{subscription_id}"'
            )

            logging.info(
                f"Succeeded to Assign role to ServicePrincipal: in {i + 1} times trial"
            )
            break
        except subprocess.CalledProcessError as e:
            logging.debug(
                f"Failed in {i + 1} times retry: Assign role to ServicePrincipal"
            )
            logging.debug(f"Error Info: {e.stderr}")
            time.sleep(5)
            continue


if __name__ == "__main__":
    # Main Function
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(format=_fmt, datefmt=_datefmt, level=logging.INFO)

    # Step 0. parse input, get service_principal_objectid
    args = _init_arg_parser()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    role_name = args.role
    service_principal_name = args.service_principal
    subscription_id = args.subscriptionId
    service_principal_objectid = _get_service_principal_objectid(service_principal_name)

    # Step 1. Set default value for subscription_id and target role content
    subscription_id, target_role_json = _set_target_role_parameters(
        subscription_id, role_name
    )

    # step 2. Create or Update Role according to target role
    _set_target_role(target_role_json, role_name, subscription_id)

    # Step 3. assign this role to Service Principal
    _assign_role_to_service_principal(
        role_name, service_principal_name, service_principal_objectid, subscription_id
    )
