# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import Path
from time import time
from typing import Any, List

import requests
from assertpy import assert_that
from azure.devops.connection import Connection  # type: ignore
from msrest.authentication import BasicAuthentication

from lisa.executable import Tool
from lisa.util import constants, get_matched_str


class ADOArtifactsDownloader(Tool):
    __file_format = re.compile(r"format=(?P<format>.*)", re.M)

    @property
    def command(self) -> str:
        return "echo ado_artifact_download"

    def _check_exists(self) -> bool:
        return True

    @property
    def can_install(self) -> bool:
        return False

    def download(
        self,
        personal_access_token: str,
        organization_url: str,
        project_name: str,
        artifacts: List[str],
        pipeline_name: str = "",
        build_id: int = 0,
        build_name: str = "",
        timeout: int = 600,
    ) -> List[Path]:
        working_path = constants.RUN_LOCAL_WORKING_PATH
        credentials = BasicAuthentication("", personal_access_token)
        connection = Connection(base_url=organization_url, creds=credentials)

        if build_id == 0 and build_name == "":
            pipeline_runs = self._get_pipeline_runs(
                connection, pipeline_name, project_name
            )
            pipeline_run = [
                run
                for run in pipeline_runs
                if run.result == "succeeded" and run.state == "completed"
            ]
            assert_that(len(pipeline_run)).described_as(
                f"no succeeded and completed run found for pipeline {pipeline_name}"
            ).is_not_zero()
            build_id = pipeline_run[0].id

        if build_id == 0 and build_name:
            pipeline_runs = self._get_pipeline_runs(
                connection, pipeline_name, project_name
            )
            pipeline_run = [run for run in pipeline_runs if run.name == build_name]
            assert_that(len(pipeline_run)).described_as(
                f"no succeeded and completed run found for pipeline {pipeline_name}"
            ).is_not_zero()
            if (
                pipeline_run[0].result == "succeeded"
                and pipeline_run[0].state == "completed"
            ):
                self._log.debug(
                    f"the job with name {build_name} exists, and it is succeeded"
                    " and completed"
                )
            else:
                self._log.debug(
                    f"the job with name {build_name} exists, but it is not succeeded"
                    " or completed"
                )
            build_id = pipeline_run[0].id

        build_client = connection.clients_v6_0.get_build_client()
        artifacts_path: List[Path] = []
        chunk_size = 1024 * 1024
        for artifact_name in artifacts:
            build_artifact = build_client.get_artifact(
                project_name, build_id, artifact_name
            )
            download_url = build_artifact.resource.download_url
            self._log.debug(f"artifact download url: {download_url}")
            working_path.mkdir(parents=True, exist_ok=True)
            file_extension = get_matched_str(download_url, self.__file_format)
            artifact_path = working_path / f"{build_artifact.name}.{file_extension}"
            self._log.debug(
                f"start to download artifact {artifact_name} to {artifact_path}"
            )
            with requests.get(
                download_url,
                auth=("", personal_access_token),
                timeout=timeout,
                stream=True,
            ) as response:
                if response.status_code == 200:
                    downloaded_size = 0
                    start_time = time()
                    log_interval = 30
                    next_log_time = start_time + log_interval
                    with open(artifact_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if chunk:
                                f.write(chunk)
                                downloaded_size += len(chunk)
                                current_time = time()
                                if current_time >= next_log_time:
                                    self._log.debug(
                                        f"Downloaded {downloaded_size} bytes of "
                                        f"artifact {artifact_name}"
                                    )
                                    next_log_time = current_time + log_interval
                    self._log.debug(
                        f"downloaded artifact {artifact_name} to "
                        f"{artifact_path} successfully"
                    )
                    artifacts_path.append(artifact_path)
                else:
                    self._log.error(
                        f"failed to download artifact {artifact_name}, status code: "
                        f"{response.status_code}"
                    )
        return artifacts_path

    def _get_pipeline_runs(
        self, connection: Any, pipeline_name: str, project_name: str
    ) -> Any:
        assert_that(pipeline_name).described_as(
            "pipeline_name should not be empty when build_id is not provided"
        ).is_not_empty()

        pipeline_client = connection.clients_v6_0.get_pipelines_client()
        pipelines = pipeline_client.list_pipelines(project_name)

        if pipeline_name:
            found_pipeline = False
            pipeline = None
            for pipeline in pipelines:
                if pipeline.name == pipeline_name:
                    found_pipeline = True
                    break
            assert_that(found_pipeline).described_as(
                (
                    f"cannot found pipeline {pipeline_name} in project "
                    f"{project_name}, please double check the names"
                )
            ).is_true()
            assert pipeline is not None, "pipeline cannot be None"
            pipeline_runs = pipeline_client.list_runs(
                pipeline_id=pipeline.id, project=project_name
            )
            assert_that(len(pipeline_runs)).described_as(
                f"no runs found for pipeline {pipeline_name}"
            ).is_not_zero()
            return pipeline_runs
