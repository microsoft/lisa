# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# This script is to create/update quota limit for the specified compute resource provided in a json file.
# Debug sample: .\request_quota.py -s "subscription_id" -l "location" -f "usage_counter.json" -d
# The josn file should have the following format, for example:
# {
#     "standardDSv2Family": 12,
#     "StandardNCADSA100v4Family": 24,
#     "experimentalOverlakeFamily": 128,
#     "standardNCSv3Family": 24
# }

import json
import logging
import time
from argparse import ArgumentParser, Namespace
from typing import Any, Dict
from .common import LOGFORMAT, DATEFMT, execute


def _init_arg_parser() -> Namespace:
    parser = ArgumentParser(
        description="Create/Update the quota limit for the specified compute resource provided in a json file"
    )
    parser.add_argument(
        "-s",
        "--subscriptionId",
        default="",
        help="Subscription scope the quota request for(default is current subscription)",
    )
    parser.add_argument(
        "-l",
        "--location",
        default="",
        help="location scope the quota request for(default is westus3)",
    )
    parser.add_argument(
        "-f",
        "--filePath",
        default="",
        help="File path provides the compute resource and limit",
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


def _load_resource_request_from_file(file_path: str) -> dict[str, int]:
    logging.info(f"Loading resource request from file: {file_path}...")
    resources: dict[str, int] = {}

    with open(file_path, "r") as file:
        resources = json.load(file)
    for sku, limit in resources.items():
        logging.info(f"Resource sku: {sku}, Limit: {limit}")

    return resources


def _call_quota_rest_api(
    subscription_id: str,
    location: str,
    provider_type: str,
    resource_name: str,
    method: str,
    body: str = None,
) -> Any:
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}/providers"
        f"/Microsoft.Compute/locations/{location}/providers/Microsoft.Quota"
        f"/{provider_type}/{resource_name}?api-version=2023-02-01"
    )

    command = f"az rest --method {method} --uri {url}"
    logging.info(f"calling REST API: {url}")

    if body:
        command = f'{command} --body "{body}" --headers "Content-Type=application/json"'

    result = execute(command=command)
    if result:
        print()
        print(result)
    else:
        logging.info("no result returned, please check later.")

    return result


def _create_quota_requests(
    subscription_id: str, location: str, resources: dict[str, int]
) -> Dict[str, Dict[str, int]]:
    requests: Dict[str, Dict[str, int]] = {}
    logging.info("Creating quota requests...")
    for sku, limit in resources.items():
        # get the current limit for the sku
        result = _call_quota_rest_api(
            subscription_id=subscription_id,
            location=location,
            provider_type="quotas",
            resource_name=sku,
            method="GET",
        )
        if result:
            current_limit = result["value"][0]["properties"]["limit"]
            if current_limit < limit:
                logging.info(f"Current limit for sku {sku} is {current_limit}")
                result["value"][0]["properties"]["limit"] = limit
                json_body = json.dumps(result)
                request = _call_quota_rest_api(
                    subscription_id=subscription_id,
                    location=location,
                    provider_type="quotas",
                    resource_name=sku,
                    method="PUT",
                    body=json_body,
                )
                request_id = request["value"][0]["name"]
                requests[request_id] = {sku: limit}
                logging.info(
                    f"Created quota request for sku: {sku}, Limit: {limit}. Request id is {request_id}"
                )
    return requests


def _wait_requests_completed(
    subscription_id: str, location: str, requests: Dict[str, dict[str, int]]
) -> None:
    logging.info("waiting for the requests completed...")

    sleep_interval = 5
    time_out = 1800
    start_time = time.time()
    succeed_requests = []
    failed_requests = []
    while time.time() - start_time < time_out:
        logging.info("Checking status of requests...")
        for id, request in requests.items():
            result = _call_quota_rest_api(
                subscription_id=subscription_id,
                location=location,
                provider_type="quotaRequests",
                resource_name=id,
                method="GET",
            )
            if result:
                status = result["value"][0]["properties"]["provisioningState"]
                logging.info(f"Request {id} status is {status}")
                if status == "Succeeded":
                    succeed_requests.append(request)
                    requests.pop(id)
                elif status == "Failed":
                    failed_requests.append(request)
                    requests.pop(id)
                    error_code = result["value"][0]["properties"]["error"]["code"]
                    message = result["value"][0]["properties"]["error"]["message"]
                    logging.info(
                        f"Request for sku {request} failed. Error code: {error_code}, Message: {message}"
                    )
            time.sleep(sleep_interval)
        if not requests:
            break

    elapsed_time = time.time() - start_time
    logging.info(f"Quota requests completed in {elapsed_time} sec")
    logging.info(f"Success requests: {succeed_requests}")
    logging.info(
        f"Failed requests: {failed_requests}. For these failed requests, please contact Azure support."
    )


if __name__ == "__main__":
    # Main Function
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(format=LOGFORMAT, datefmt=DATEFMT, level=logging.INFO)

    # Step 0. parse input, get subscription_id, location and resources
    # that need to be updated or created
    args = _init_arg_parser()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    location = args.location
    subscription_id = args.subscriptionId
    resources: dict[str, int] = _load_resource_request_from_file(file_path)

    # Step 1. create resource quota requests
    requests = _create_quota_requests(subscription_id, location, resources)

    # step 2. wait all the requests completed
    _wait_requests_completed(subscription_id, location, requests)
