# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import base64
import datetime
import re
import uuid
from pathlib import Path
from typing import Any, List, Optional, cast

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
from lisa.features import Disk, DiskPremiumSSDLRS
from lisa.operating_system import Posix
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.tools import Find, Lsblk, Wget
from lisa.util import SkippedException


def _add_data_disk(log: Logger, node: Node, size_in_gb: int) -> str:
    disk = node.features[Disk]
    lsblk = node.tools[Lsblk]

    # get partition info before adding data disk
    partitions_before_adding_disk = lsblk.get_disks(force_run=True)
    data_disk = disk.add_data_disk(
        count=1,
        disk_type=schema.DiskType.PremiumSSDLRS,
        size_in_gb=size_in_gb,
    )
    log.info(f"Added disk '{data_disk}' of size '{size_in_gb}'GB")
    partitons_after_adding_disk = lsblk.get_disks(force_run=True)
    added_partitions = [
        item
        for item in partitons_after_adding_disk
        if item not in partitions_before_adding_disk
    ]
    assert_that(added_partitions, "Data disk should be added").is_length(1)
    disk_name = added_partitions[0].name
    log.info(f"Disk name : '{disk_name}'")
    return disk_name


def _remove_data_disk(log: Logger, node: Node) -> None:
    disk = node.features[Disk]
    disk.remove_data_disk()
    log.info("Detached all data disks")


def _init_disk(log: Logger, node: Node) -> List[str]:
    data_disk1 = _add_data_disk(log=log, node=node, size_in_gb=1)
    data_disk2 = _add_data_disk(log=log, node=node, size_in_gb=10)
    return [data_disk1, data_disk2]


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
    os = ""
    for component_status in split_status:
        if component_status is not None:
            if component_status.find("osidentifier") != -1:
                log.info(f"Component status : '{component_status}'")
                os_encoded = re.split(":", component_status)[-1]
                os = base64.b64decode(os_encoded).decode()

    assert_that(os).described_as(
        "Expected OS information to be extracted"
    ).is_not_empty()
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
    node: Node,
    log: Logger,
    test_dir: str,
    cvt_script: CustomScriptBuilder,
    data_disks: List[str],
) -> ExecutableResult:
    timer = create_timer()
    script: CustomScript = node.tools[cvt_script]
    # Convert script to unix line endings
    posix_os: Posix = cast(Posix, node.os)
    posix_os.install_packages("dos2unix")
    dos2unix_result = node.execute(
        f"dos2unix '{script._command}'",
        cwd=script._cwd,
        shell=True,
        sudo=True,
    )
    assert_that(dos2unix_result.exit_code).described_as(
        "Failed to modify shell script to unix format"
    ).is_equal_to(0)

    params = test_dir + " /dev/" + data_disks[0] + " /dev/" + data_disks[1]
    result = script.run(
        parameters=params,
        timeout=19800,
        shell=True,
        sudo=True,
    )
    log.info(f"Script run with param {params} finished within {timer}")
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
    container_sas_uri: str,
    os: str,
    cvt_script: CustomScriptBuilder,
    data_disks: List[str],
) -> Optional[int]:
    cvt_bin = "indskflt_ct"
    max_log_length = 200
    cvt_binary_sas_uri = container_sas_uri.replace(
        "?", "/cvtbinaries/indskflt_ct_" + os + "?"
    )

    cvt_download_dir = str(node.working_path) + "/cvt_files/"

    wget = node.tools[Wget]

    download_path = wget.get(
        url=f"{cvt_binary_sas_uri}",
        filename=cvt_bin,
        file_path=cvt_download_dir,
        sudo=True,
    )

    cvt_md5sum = node.execute(f"md5sum {download_path}", shell=True, sudo=True)
    log.info(f"md5sum '{download_path}' : '{cvt_md5sum}'")

    result = _run_script(
        node=node,
        log=log,
        test_dir=cvt_download_dir,
        cvt_script=cvt_script,
        data_disks=data_disks,
    )
    cvt_stdout = result.stdout
    if len(cvt_stdout) > max_log_length:
        cvt_stdout = cvt_stdout[:max_log_length]
    cvt_stderr = result.stderr
    if len(cvt_stderr) > max_log_length:
        cvt_stderr = cvt_stderr[:max_log_length]
    log.info(f"cvt script stdout : '{cvt_stdout}'")
    log.info(f"cvt script stderr : '{cvt_stderr}'")
    log.info(f"cvt script exit code : '{result.exit_code}'")
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

        Downgrade the case priority from 3 to 5 for its instability.
        """,
        priority=5,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
            disk=DiskPremiumSSDLRS(),
        ),
    )
    def verify_asr_by_cvt(
        self,
        node: Node,
        log: Logger,
        log_path: Path,
    ) -> None:
        os = _get_os_info_from_extension(node=node, log=log)
        if not os:
            raise SkippedException("Failed to determine the OS.")
        _install_asr_extension_distro(node=node, log=log, os=os)
        result = _run_cvt_tests(
            node=node,
            log=log,
            log_path=log_path,
            container_sas_uri=self._container_sas_uri,
            os=os,
            cvt_script=self._cvt_script,
            data_disks=self._data_disks,
        )
        log.info(f"ASR CVT test completed with exit code '{result}'")
        assert_that(result).described_as("ASR CVT test failed").is_equal_to(0)

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        variables = kwargs["variables"]
        node = kwargs["node"]
        self._container_sas_uri = variables.get("cvtbinaries_sasuri", "")
        if not self._container_sas_uri:
            raise SkippedException("cvtbinaries_sasuri is not provided.")

        self._cvt_script = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"), ["cvt.sh"]
        )
        self._data_disks = _init_disk(node=node, log=log)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        _remove_data_disk(node=node, log=log)
