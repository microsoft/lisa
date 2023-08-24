# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import base64
import datetime
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from assertpy import assert_that

from lisa import (
    CustomScript,
    CustomScriptBuilder,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    create_timer,
    schema,
    simple_requirement,
)
from lisa.executable import ExecutableResult
from lisa.features import Disk
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.tools import Find, Mkdir, Wget
from lisa.util import SkippedException


def _init_disk(log: Logger, node: Node) -> None:
    disk = node.features[Disk]
    log.info("Adding 1st managed disk of size 1GB")
    disk.add_data_disk(1, schema.DiskType.PremiumSSDLRS, 1)
    log.info("Adding 2nd managed disk of size 10GB")
    disk.add_data_disk(1, schema.DiskType.PremiumSSDLRS, 10)


def _get_extension_name(log: Logger, os: str) -> str:
    # UBUNTU-22.04-64
    distro = os[:-3]
    distro = "".join(re.findall(r"[A-Z0-9]", distro))
    extension_name = "Linux" + distro
    log.info(f"Extension name : '{extension_name}'")
    return extension_name


def _get_os_info_from_extension(log: Logger, node: Node) -> str:
    task_id = str(uuid.uuid4())
    cur_time = datetime.datetime.now().isoformat() + "Z"
    extension_name = "Microsoft.Azure.RecoveryServices.SiteRecovery.Linux"
    settings = {
        "publicObject": "",
        "module": "a2a",
        "timeStamp": cur_time,
        "commandToExecute": "GetOsDetails",
        "taskId": task_id,
    }
    extension = node.features[AzureExtension]

    result = extension.create_or_update(
        name=extension_name,
        publisher="Microsoft.Azure.RecoveryServices.SiteRecovery",
        type_="Linux",
        type_handler_version="1.0",
        auto_upgrade_minor_version=True,
        settings=settings,
    )
    assert_that(result["provisioning_state"]).described_as(
        "Expected the extension to succeed"
    ).is_equal_to("Succeeded")

    extension_instance_view = extension.get(
        name=extension_name,
    ).instance_view

    extension_substatus = ""
    for substatus in extension_instance_view.substatuses:
        log.info(f"Substatus : '{substatus}'")
        code = substatus.code
        if code is not None and code.find("platform") != -1:
            extension_substatus = code
            break
    if not extension_substatus:
        return extension_substatus

    log.info(f"Substatus : '{extension_substatus}'")
    split_status = re.split(",|/", extension_substatus)
    for component_status in split_status:
        if component_status is not None:
            if component_status.find("osidentifier") != -1:
                log.info(f"Component status : '{component_status}'")
                os_encoded = re.split(":", component_status)[-1]
                os = base64.b64decode(os_encoded).decode()

    log.info(f"os : '{os}'")
    return os


def _install_asr_extension_distro(log: Logger, node: Node, os: str) -> None:
    task_id = str(uuid.uuid4())
    extension_publishers = {
        "SLES11-SP3-64",
        "SLES11-SP4-64",
        "RHEL6-64",
        "RHEL7-64",
        "UBUNTU-14.04-64",
        "UBUNTU-16.04-64",
        "OL6-64",
        "OL7-64",
    }
    extension_test = {
        "SLES11-SP3-64",
        "SLES11-SP4-64",
        "OL6-64",
        "RHEL7-64",
    }
    publisher_name = "Microsoft.Azure.SiteRecovery.Test"
    extension_name = _get_extension_name(os=os, log=log)
    if os in extension_publishers:
        if os in extension_test:
            extension_name = extension_name + "Test"
    else:
        publisher_name = "Microsoft.Azure.SiteRecovery2.Test"

    cur_time = datetime.datetime.now().isoformat() + "Z"
    settings = {
        "publicObject": "",
        "module": "a2a",
        "timeStamp": cur_time,
        "commandToExecute": "Install",
        "taskId": task_id,
    }
    extension = node.features[AzureExtension]

    result = extension.create_or_update(
        name=publisher_name + "." + extension_name,
        publisher=publisher_name,
        type_=extension_name,
        type_handler_version="1.0",
        auto_upgrade_minor_version=True,
        settings=settings,
    )
    assert_that(result["provisioning_state"]).described_as(
        "Expected the extension to succeed"
    ).is_equal_to("Succeeded")


def _run_script(
    node: Node, log: Logger, test_dir: str, cvt_script: CustomScriptBuilder
) -> ExecutableResult:
    timer = create_timer()
    script: CustomScript = node.tools[cvt_script]
    result = script.run(parameters=test_dir, timeout=19800, sudo=True)
    log.info(f"Script run with param {test_dir} finished within {timer}")
    return result


def _copy_cvt_logs(
    log: Logger,
    log_path: Path,
    node: Node,
    test_dir: Path,
) -> None:
    find_tool = node.tools[Find]
    file_list = find_tool.find_files(
        test_dir,
        name_pattern="*.log",
        file_type="f",
        sudo=True,
        ignore_not_exist=True,
    )

    file_list += find_tool.find_files(
        test_dir,
        name_pattern="*.txt",
        file_type="f",
        sudo=True,
        ignore_not_exist=True,
    )

    for file in file_list:
        log.info(f"Copying file {file} to {log_path}")
        try:
            file_name = file.split("/")[-1]
            node.shell.copy_back(
                node.get_pure_path(file),
                log_path / f"{file_name}",
            )
        except FileNotFoundError:
            log.error(f"File {file} doesn't exist.")


def _run_cvt_tests(
    log: Logger,
    node: Node,
    log_path: Path,
    variables: Dict[str, Any],
    os: str,
    cvt_script: CustomScriptBuilder,
) -> Optional[int]:
    cvt_bin = "indskflt_ct"
    container_sas_uri = variables.get("cvtbinaries_sasuri", "")
    if not container_sas_uri:
        log.error("sas uri for cvt binary is empty.")
        raise SkippedException("sas uri for cvt binary is empty.")
    cvt_binary_sas_uri = container_sas_uri.replace(
        "?", "/cvtbinaries/indskflt_ct_" + os + "?"
    )

    cvt_root_dir = str(node.working_path) + "/LisaTest/"
    cvt_download_dir = cvt_root_dir + "cvt_files/"

    mkdir = node.tools[Mkdir]
    wget = node.tools[Wget]

    mkdir.create_directory(cvt_download_dir, sudo=True)
    download_path = wget.get(
        url=f"{cvt_binary_sas_uri}",
        filename=cvt_bin,
        file_path=cvt_download_dir,
        sudo=True,
    )

    cvt_md5sum = node.execute(f"md5sum {download_path}", shell=True, sudo=True)
    log.info(f"md5sum '{download_path}' : '{cvt_md5sum}'")

    result = _run_script(
        node=node, log=log, test_dir=cvt_download_dir, cvt_script=cvt_script
    )
    _copy_cvt_logs(
        node=node,
        log=log,
        test_dir=Path(node.working_path),
        log_path=log_path,
    )
    return result.exit_code


@TestSuiteMetadata(
    area="cvt",
    category="functional",
    description="""
    This test is used to validate the functionality of ASR driver.
    """,
    requirement=simple_requirement(unsupported_os=[]),
)
class CVTTest(TestSuite):
    TIMEOUT = 21600

    @TestCaseMetadata(
        description="""
        this test validate the functionality of ASR driver by verifying
        integrity of a source disk with respect to a target disk
        """,
        priority=1,
        timeout=TIMEOUT,
    )
    def verify_asr_by_cvt(
        self,
        node: Node,
        log: Logger,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        _init_disk(node=node, log=log)
        os = _get_os_info_from_extension(node=node, log=log)
        _install_asr_extension_distro(node=node, log=log, os=os)
        result = _run_cvt_tests(
            node=node,
            log=log,
            log_path=log_path,
            variables=variables,
            os=os,
            cvt_script=self._cvt_script,
        )
        log.info(f"ASR CVT test completed with exit code '{result}'")
        assert_that(result).described_as("ASR CVT test failed").is_equal_to(0)

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        self._cvt_script = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"), ["cvt.sh"]
        )
        log.info("before test case")
