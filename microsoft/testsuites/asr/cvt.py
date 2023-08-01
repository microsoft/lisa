# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from assertpy import assert_that

from pathlib import Path, PurePath, PurePosixPath

import datetime
import uuid
import json
import base64

from azure.mgmt.compute.models import (
    VirtualMachineExtensionInstanceView,
    InstanceViewStatus,
)
from lisa.sut_orchestrator.azure.features import AzureExtension

from lisa.features import Disk

from lisa import (
    Logger,
    Node,
    CustomScript,
    CustomScriptBuilder,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
    schema,
    create_timer,
)
from lisa.operating_system import Posix
from lisa.tools import Echo, Uname, Ls, Mkdir, Wget, Find
import re

@TestSuiteMetadata(
    area="cvt",
    category="functional",
    description="""
    This test is used to validate the functionality of ASR driver.
    """,
    requirement=simple_requirement(unsupported_os=[]),
)
class CVTTest(TestSuite):
    TIMEOUT = 12000

    def init_disk(
        self,
        log: Logger,
        node: Node
    ) -> None:

        disk = node.features[Disk]
        log.info("Adding 1st managed disk of size 1GB")
        data_disk1 = disk.add_data_disk(1, schema.DiskType.PremiumSSDLRS, 1)
        log.info("Adding 2nd managed disk of size 10GB")
        data_disk1 = disk.add_data_disk(1, schema.DiskType.PremiumSSDLRS, 10)


    def get_extension_name(
        self,
        log: Logger,
        os: str
    ) -> None:

        #UBUNTU-22.04-64
        distro = os[:-3]
        distro = "".join(re.findall(r'[A-Z0-9]', distro))
        extension_name = "Linux" +  distro
        log.info(f"Extension name : '{extension_name}'")
        return extension_name


    def install_asr_extension_common(
        self,
        log: Logger,
        node: Node
    ) -> None:

        task_id = str(uuid.uuid4())
        cur_time = datetime.datetime.now().isoformat() + 'Z'
        settings = {
            "publicObject": "",
            "module": "a2a",
            "timeStamp": cur_time,
            "commandToExecute": "GetOsDetails",
            "taskId": task_id
        }
        extension = node.features[AzureExtension]

        result = extension.create_or_update(
            name="Linux",
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
            name="Linux",
        ).instance_view

        extension_substatus = "";
        for substatus in extension_instance_view.substatuses:
            log.info(f"Substatus : '{substatus}'")
            code = substatus.code
            if code is not None and code.find("platform") != -1:
                extension_substatus = code
                break
        if not extension_substatus:
            return extension_substatus

        log.info(f"Substatus : '{extension_substatus}'")
        split_status = re.split(',|/', extension_substatus)
        for component_status in split_status:
            if component_status is not None and component_status.find("osidentifier") != -1:
                log.info(f"Component status : '{component_status}'")
                OS = base64.b64decode(re.split(':', component_status)[-1]).decode()

        log.info(f"OS : '{OS}'")
        return OS


    def install_asr_extension_distro(
        self,
        log: Logger,
        node: Node,
        os: str
    ) -> None:

        task_id = str(uuid.uuid4())
        extension_publishers = {
            "SLES11-SP3-64",
            "SLES11-SP4-64",
            "RHEL6-64",
            "RHEL7-64",
            "UBUNTU-14.04-64",
            "UBUNTU-16.04-64",
            "OL6-64",
            "OL7-64"
        }
        extension_test = {
            "SLES11-SP3-64",
            "SLES11-SP4-64",
            "OL6-64",
            "RHEL7-64"
        }
        #publisher_name = "Microsoft.Azure.RecoveryServices.SiteRecovery"
        publisher_name = "Microsoft.Azure.SiteRecovery.Test"
        extension_name = self.get_extension_name(os=os, log=log)
        if os in extension_publishers:
            if os in extension_test:
                extension_name = extension_name + "Test"
        else:
            publisher_name = "Microsoft.Azure.SiteRecovery2.Test"

        cur_time = datetime.datetime.now().isoformat() + 'Z'
        settings = {
            "publicObject": "",
            "module": "a2a",
            "timeStamp": cur_time,
            "commandToExecute": "Install",
            "taskId": task_id
        }
        extension = node.features[AzureExtension]


        result = extension.create_or_update(
            name=extension_name,
            publisher=publisher_name,
            type_=extension_name,
            type_handler_version="1.0",
            auto_upgrade_minor_version=True,
            settings=settings,
        )
        assert_that(result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")


    def run_script(self, node: Node, log: Logger, test_dir: str) -> None:
        timer = create_timer()
        script: CustomScript = node.tools[self._cvt_script]
        result = script.run(parameters=test_dir, timeout=19800, sudo=True)
        log.info(f"Script run with param {test_dir} finished within {timer}")
        return result


    def copy_cvt_logs(
        self,
        log: Logger,
        node: Node,
        test_dir : Path,
        log_path : Path
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

    def run_cvt_tests(
        self,
        log: Logger,
        node: Node,
        log_path: Path,
        variables: Dict[str, Any]
    ) -> None:
        cvt_bin = "indskflt_ct"
        sas_uri = variables.get("cvt_binary_sas_uri", "")
        cvt_root_dir = str(node.working_path) + '/LisaTest/'
        cvt_download_dir = cvt_root_dir + 'cvt_files/'
        cvt_bin_path = cvt_download_dir + cvt_bin

        mkdir = node.tools[Mkdir]
        wget = node.tools[Wget]
        ls = node.tools[Ls]

        mkdir.create_directory(cvt_download_dir, sudo=True)

        download_path = wget.get(
            url=f"{sas_uri}", filename=cvt_bin, file_path=cvt_download_dir, sudo=True
        )

        cvt_md5sum = node.execute(
            f"md5sum {download_path}", shell=True, sudo=True
        )
        log.info(f"md5sum '{download_path}' : '{cvt_md5sum}'")

        result = self.run_script(node=node, log=log, test_dir=cvt_download_dir)
        self.copy_cvt_logs(node=node, log=log, test_dir=node.working_path.parent.parent, log_path=log_path)
        return result


    @TestCaseMetadata(
        description="""
        this test validate the functionality of ASR driver by verifying
        integrity of a source disk with respect to a target disk
        """,
        priority=0,
        use_new_environment=True,
        timeout=TIMEOUT
    )
    def run_cvt(
        self,
        node: Node,
        log: Logger,
        log_path: Path,
        variables: Dict[str, Any]
    ) -> None:

        info = node.tools[Uname].get_linux_information()
        log.info(
            f"release: '{info.uname_version}', "
            f"version: '{info.kernel_version_raw}', "
            f"hardware: '{info.hardware_platform}', "
            f"os: '{info.operating_system}'"
        )

        self.init_disk(node=node, log=log)
        OS = self.install_asr_extension_common(node=node, log=log)
        self.install_asr_extension_distro(node=node, log=log, os=OS)
        result = self.run_cvt_tests(node=node, log=log, log_path=log_path, variables=variables)
        assert_that(result.exit_code).is_equal_to(0)

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        self._cvt_script = CustomScriptBuilder(
            Path(__file__).parent.joinpath("scripts"), ["cvt.sh"]
        )
        log.info("before test case")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        log.info("after test case")

