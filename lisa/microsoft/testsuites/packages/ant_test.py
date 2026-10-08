# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Release-gate tests for ant on Azure Linux.

Each case verifies one reviewed behaviour obligation directly against the
node under test. Generated from a reviewed behaviour corpus (IR).

Every case declares the same timeout of 120 seconds.
Bounds a hang only: the slowest measured case finishes in 17.32 seconds.
"""

from __future__ import annotations

from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner
from lisa.tools import Cat, Chmod, Ls, Mkdir, Rm, Stat, Tee
from lisa.util import SkippedException, UnsupportedDistroException


@TestSuiteMetadata(
    area="packages",
    category="functional",
    description="Release-gate tests for ant on Azure Linux.",
    tags=["ai-generated"],
    owner="azurelinux",
    requirement=simple_requirement(supported_os=[CBLMariner]),
    maturity="preview",
)
class AntSuite(TestSuite):
    """Release-gate behaviour tests for ant."""

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        """Prepare the guest this suite's material was verified on."""
        node: Node = kwargs["node"]
        if not isinstance(node.os, CBLMariner) or node.os.information.version < "4.0.0":
            raise SkippedException(
                UnsupportedDistroException(
                    node.os,
                    "This suite is supported only on Azure Linux 4.0.0 or later.",
                )
            )
        node.os.install_packages(
            [
                "ant",
                "java-25-openjdk-devel",
                "java-25-openjdk-headless",
            ]
        )

    @TestCaseMetadata(
        description=(
            "Ant creates usable JARs from selected files with a supplied\n"
            "manifest, and remains usable when no manifest or no matching\n"
            "files are supplied.\n"
            "\n"
            "Corpus obligation: pkg:ant/archive-workflows/jar-manifest\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_archive_workflows_jar_manifest(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/archive-workflows/jar-manifest."""
        log.info("Verifying obligation pkg:ant/archive-workflows/jar-manifest")
        workdir = node.get_pure_path(f"/tmp/lisa-ant-jar-manifest-{node.name}")
        node.tools[Mkdir].create_directory(str(workdir))
        try:
            selected_dir = workdir / "selected"
            payload_path = selected_dir / "payload.txt"
            manifest_path = workdir / "custom.mf"
            build_path = workdir / "build.xml"
            extracted_manifest = workdir / "META-INF" / "MANIFEST.MF"
            node.tools[Mkdir].create_directory(str(selected_dir))
            node.tools[Tee].write_to_file(
                "selected payload",
                payload_path,
            )
            node.tools[Tee].write_to_file(
                "Manifest-Version: 1.0\nLISA-Supplied: present\n",
                manifest_path,
            )
            build_text = (
                '<project name="jar-manifest" default="archives">\n'
                '  <target name="archives">\n'
                '    <jar destfile="supplied.jar" manifest="custom.mf" '
                'basedir="selected"/>\n'
                '    <jar destfile="simple.jar" basedir="selected"/>\n'
                '    <jar destfile="empty.jar" basedir="selected" '
                'includes="absent.bin"/>\n'
                "  </target>\n"
                "</project>"
            )
            node.tools[Tee].write_to_file(build_text, build_path)
            node.execute(
                "ant",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant should create supplied, simple, and manifest-only JARs"
                ),
            )
            supplied_result = node.execute(
                "jar tf supplied.jar",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "the JAR with the supplied manifest should be readable"
                ),
            )
            supplied_listing = f"{supplied_result.stdout}\n{supplied_result.stderr}"
            assert_that(supplied_listing).described_as(
                "the supplied-manifest JAR contains the selected file"
            ).contains("payload.txt")
            assert_that(supplied_listing).described_as(
                "the supplied-manifest JAR contains a manifest"
            ).contains("META-INF/MANIFEST.MF")
            simple_result = node.execute(
                "jar tf simple.jar",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "the JAR without a supplied manifest should be readable"
                ),
            )
            simple_listing = f"{simple_result.stdout}\n{simple_result.stderr}"
            assert_that(simple_listing).described_as(
                "the simple JAR contains the selected file"
            ).contains("payload.txt")
            assert_that(simple_listing).described_as(
                "the simple JAR contains Ant provided manifest metadata"
            ).contains("META-INF/MANIFEST.MF")
            empty_result = node.execute(
                "jar tf empty.jar",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "the JAR with no matching files should still be readable"
                ),
            )
            empty_listing = f"{empty_result.stdout}\n{empty_result.stderr}"
            assert_that(empty_listing).described_as(
                "the no-match JAR omits the unselected payload"
            ).does_not_contain("payload.txt")
            assert_that(empty_listing).described_as(
                "the no-match JAR retains its available manifest"
            ).contains("META-INF/MANIFEST.MF")
            node.execute(
                "jar xf supplied.jar META-INF/MANIFEST.MF",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "the supplied manifest should be extractable"
                ),
            )
            supplied_manifest = node.tools[Cat].read(str(extracted_manifest))
            assert_that(supplied_manifest).described_as(
                "the first JAR uses the user supplied manifest"
            ).contains("LISA-Supplied: present")
            node.tools[Rm].remove_directory(str(workdir / "META-INF"))
            node.execute(
                "jar xf simple.jar META-INF/MANIFEST.MF",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant provided simple manifest should be extractable"
                ),
            )
            simple_manifest = node.tools[Cat].read(
                str(extracted_manifest),
                force_run=True,
            )
            assert_that(simple_manifest).described_as(
                "the second JAR does not reuse the supplied manifest"
            ).does_not_contain("LISA-Supplied: present")
            assert_that(simple_manifest).described_as(
                "the second JAR carries the simple manifest supplied by Ant"
            ).contains("Manifest-Version: 1.0", "Ant-Version:")
            node.tools[Rm].remove_directory(str(workdir / "META-INF"))
            node.execute(
                "jar xf empty.jar META-INF/MANIFEST.MF",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "the no-match JAR manifest should be extractable"
                ),
            )
            empty_manifest = node.tools[Cat].read(
                str(extracted_manifest),
                force_run=True,
            )
            assert_that(empty_manifest).described_as(
                "the no-match JAR contains Ant provided manifest metadata"
            ).contains("Manifest-Version: 1.0", "Ant-Version:")
        finally:
            node.tools[Rm].remove_directory(str(workdir))

    @TestCaseMetadata(
        description=(
            "ZIP, WAR, and JAR extraction can narrow output through patterns\n"
            "and transform output names through a mapper.\n"
            "\n"
            "Corpus obligation: pkg:ant/archive-workflows/patterned-extraction\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_archive_workflows_patterned_extraction(
        self, node: Node, log: Logger
    ) -> None:
        """Verify obligation pkg:ant/archive-workflows/patterned-extraction."""
        log.info("Verifying obligation pkg:ant/archive-workflows/patterned-extraction")
        workdir = node.get_pure_path(f"/tmp/lisa-ant-patterned-extraction-{node.name}")
        node.tools[Mkdir].create_directory(str(workdir))
        try:
            input_dir = workdir / "input"
            node.tools[Mkdir].create_directory(str(input_dir))
            node.tools[Tee].write_to_file("MATCHED_PAYLOAD", input_dir / "match.txt")
            node.tools[Tee].write_to_file("OTHER_PAYLOAD", input_dir / "skip.bin")
            node.tools[Chmod].chmod(str(input_dir / "match.txt"), "700")
            node.tools[Chmod].chmod(str(input_dir / "skip.bin"), "700")
            source_mode = node.tools[Stat].get_file_permission(
                str(input_dir / "match.txt")
            )
            assert_that(source_mode).described_as(
                "archive input has the distinctive permission to contrast"
            ).is_equal_to(700)
            build = (
                '<project name="patterned-extraction" default="make">\n'
                '  <target name="make">\n'
                '    <zip destfile="sample.zip">\n'
                '      <zipfileset dir="input" filemode="700"/>\n'
                "    </zip>\n"
                '    <zip destfile="sample.war">\n'
                '      <zipfileset dir="input" filemode="700"/>\n'
                "    </zip>\n"
                '    <zip destfile="sample.jar">\n'
                '      <zipfileset dir="input" filemode="700"/>\n'
                "    </zip>\n"
                "  </target>\n"
                '  <target name="zip-all">\n'
                '    <unzip src="sample.zip" dest="zip-all"/>\n'
                "  </target>\n"
                '  <target name="war-all">\n'
                '    <unwar src="sample.war" dest="war-all"/>\n'
                "  </target>\n"
                '  <target name="jar-all">\n'
                '    <unjar src="sample.jar" dest="jar-all"/>\n'
                "  </target>\n"
                '  <target name="zip-pattern">\n'
                '    <unzip src="sample.zip" dest="zip-pattern">\n'
                '      <patternset><include name="*.txt"/></patternset>\n'
                '      <globmapper from="*" to="mapped-*.out"/>\n'
                "    </unzip>\n"
                "  </target>\n"
                '  <target name="war-pattern">\n'
                '    <unwar src="sample.war" dest="war-pattern">\n'
                '      <patternset><include name="*.txt"/></patternset>\n'
                '      <globmapper from="*" to="mapped-*.out"/>\n'
                "    </unwar>\n"
                "  </target>\n"
                '  <target name="jar-pattern">\n'
                '    <unjar src="sample.jar" dest="jar-pattern">\n'
                '      <patternset><include name="*.txt"/></patternset>\n'
                '      <globmapper from="*" to="mapped-*.out"/>\n'
                "    </unjar>\n"
                "  </target>\n"
                "</project>"
            )
            node.tools[Tee].write_to_file(build, workdir / "build.xml")
            node.execute(
                "ant -f build.xml make",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed to create the controlled archives"
                ),
            )
            node.execute(
                "ant -f build.xml zip-all",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed to extract the ZIP without a pattern"
                ),
            )
            node.execute(
                "ant -f build.xml war-all",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed to extract the WAR without a pattern"
                ),
            )
            node.execute(
                "ant -f build.xml jar-all",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed to extract the JAR without a pattern"
                ),
            )
            all_outputs = (
                ("ZIP", workdir / "zip-all" / "match.txt", "MATCHED_PAYLOAD"),
                ("ZIP", workdir / "zip-all" / "skip.bin", "OTHER_PAYLOAD"),
                ("WAR", workdir / "war-all" / "match.txt", "MATCHED_PAYLOAD"),
                ("WAR", workdir / "war-all" / "skip.bin", "OTHER_PAYLOAD"),
                ("JAR", workdir / "jar-all" / "match.txt", "MATCHED_PAYLOAD"),
                ("JAR", workdir / "jar-all" / "skip.bin", "OTHER_PAYLOAD"),
            )
            for archive_kind, output_path, marker in all_outputs:
                content = node.tools[Cat].read(str(output_path), force_run=True)
                assert_that(content).described_as(
                    f"{archive_kind} extraction without a pattern includes every file"
                ).contains(marker)
            all_mode_paths = (
                ("ZIP", workdir / "zip-all" / "match.txt"),
                ("WAR", workdir / "war-all" / "match.txt"),
                ("JAR", workdir / "jar-all" / "match.txt"),
            )
            for archive_kind, output_path in all_mode_paths:
                mode = node.tools[Stat].get_file_permission(str(output_path))
                assert_that(mode).described_as(
                    f"{archive_kind} extraction does not restore archive permissions"
                ).is_not_equal_to(700)
            node.execute(
                "ant -f build.xml zip-pattern",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed to extract the ZIP with a pattern and mapper"
                ),
            )
            node.execute(
                "ant -f build.xml war-pattern",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed to extract the WAR with a pattern and mapper"
                ),
            )
            node.execute(
                "ant -f build.xml jar-pattern",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed to extract the JAR with a pattern and mapper"
                ),
            )
            patterned_outputs = (
                ("ZIP", workdir / "zip-pattern" / "mapped-match.txt.out"),
                ("WAR", workdir / "war-pattern" / "mapped-match.txt.out"),
                ("JAR", workdir / "jar-pattern" / "mapped-match.txt.out"),
            )
            for archive_kind, output_path in patterned_outputs:
                content = node.tools[Cat].read(str(output_path), force_run=True)
                assert_that(content).described_as(
                    f"{archive_kind} pattern selects and maps the matching file"
                ).contains("MATCHED_PAYLOAD")
            excluded_outputs = (
                ("ZIP", workdir / "zip-pattern" / "match.txt"),
                ("ZIP", workdir / "zip-pattern" / "skip.bin"),
                ("ZIP", workdir / "zip-pattern" / "mapped-skip.bin.out"),
                ("WAR", workdir / "war-pattern" / "match.txt"),
                ("WAR", workdir / "war-pattern" / "skip.bin"),
                ("WAR", workdir / "war-pattern" / "mapped-skip.bin.out"),
                ("JAR", workdir / "jar-pattern" / "match.txt"),
                ("JAR", workdir / "jar-pattern" / "skip.bin"),
                ("JAR", workdir / "jar-pattern" / "mapped-skip.bin.out"),
            )
            for archive_kind, output_path in excluded_outputs:
                exists = node.tools[Ls].path_exists(str(output_path))
                assert_that(exists).described_as(
                    f"{archive_kind} patterned extraction excludes unmapped outputs"
                ).is_false()
            for archive_kind, output_path in patterned_outputs:
                mode = node.tools[Stat].get_file_permission(str(output_path))
                assert_that(mode).described_as(
                    f"{archive_kind} mapped output does not restore archive permissions"
                ).is_not_equal_to(700)
        finally:
            node.tools[Rm].remove_directory(str(workdir))

    @TestCaseMetadata(
        description=(
            "ZIP creation uses relative paths from selected filesets and\n"
            "excludes files that do not match the selection.\n"
            "\n"
            "Corpus obligation: pkg:ant/archive-workflows/zip-selection\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_archive_workflows_zip_selection(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/archive-workflows/zip-selection."""
        log.info("Verifying obligation pkg:ant/archive-workflows/zip-selection")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-zip-selection-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            input_dir = scratch / "input" / "nested"
            buildfile = scratch / "build.xml"
            selected = input_dir / "selected.keep"
            anchor = input_dir / "anchor.keep"
            blocked = input_dir / "blocked.keep"
            node.tools[Mkdir].create_directory(str(input_dir))
            build_content = (
                '<project name="zip-selection" default="first">\n'
                '  <target name="first">\n'
                '    <zip destfile="matching.zip" basedir="input"\n'
                '         includes="**/*.keep"\n'
                '         excludes="**/blocked*.keep"/>\n'
                '    <unzip src="matching.zip" dest="matching-out"/>\n'
                "  </target>\n"
                '  <target name="second">\n'
                '    <move file="input/nested/selected.keep"\n'
                '          tofile="input/nested/blocked-changed.keep"/>\n'
                '    <zip destfile="nonmatching.zip" basedir="input"\n'
                '         includes="**/*.keep"\n'
                '         excludes="**/blocked*.keep"/>\n'
                '    <unzip src="nonmatching.zip"\n'
                '           dest="nonmatching-out"/>\n'
                "  </target>\n"
                "</project>"
            )
            node.tools[Tee].write_to_file(build_content, buildfile)
            node.tools[Tee].write_to_file("selected-content", selected)
            node.tools[Tee].write_to_file("anchor-content", anchor)
            node.tools[Tee].write_to_file("blocked-content", blocked)
            node.tools[Chmod].chmod(str(input_dir), "700")
            node.tools[Chmod].chmod(str(selected), "600")
            node.tools[Chmod].chmod(str(anchor), "600")
            node.tools[Chmod].chmod(str(blocked), "600")

            node.execute(
                "ant",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed to create and extract the matching archive"
                ),
            )
            matching_listing = node.execute(
                "jar tf matching.zip",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "jar failed to list the matching archive"
                ),
            )
            matching_output = matching_listing.stdout + matching_listing.stderr
            assert_that(matching_output).described_as(
                "selected file uses its relative fileset path"
            ).contains("nested/selected.keep")
            assert_that(matching_output).described_as(
                "excluded input is absent from the matching archive"
            ).does_not_contain("nested/blocked.keep")
            matching_file_mode = node.tools[Stat].get_file_permission(
                str(scratch / "matching-out" / "nested" / "selected.keep")
            )
            matching_dir_mode = node.tools[Stat].get_file_permission(
                str(scratch / "matching-out" / "nested")
            )
            assert_that(matching_file_mode).described_as(
                "archived file does not preserve the distinctive source mode"
            ).is_not_equal_to(600)
            assert_that(matching_dir_mode).described_as(
                "archived directory does not preserve the distinctive source mode"
            ).is_not_equal_to(700)

            node.execute(
                "ant second",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed after changing the selected file to an excluded name"
                ),
            )
            nonmatching_listing = node.execute(
                "jar tf nonmatching.zip",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "jar failed to list the nonmatching archive"
                ),
            )
            nonmatching_output = nonmatching_listing.stdout + nonmatching_listing.stderr
            assert_that(nonmatching_output).described_as(
                "unchanged selected input keeps the second archive nonempty"
            ).contains("nested/anchor.keep")
            assert_that(nonmatching_output).described_as(
                "renamed nonmatching file is excluded from the second archive"
            ).does_not_contain("nested/blocked-changed.keep")
            assert_that(nonmatching_output).described_as(
                "old relative path is not retained after the input was renamed"
            ).does_not_contain("nested/selected.keep")
            nonmatching_file_mode = node.tools[Stat].get_file_permission(
                str(scratch / "nonmatching-out" / "nested" / "anchor.keep")
            )
            nonmatching_dir_mode = node.tools[Stat].get_file_permission(
                str(scratch / "nonmatching-out" / "nested")
            )
            assert_that(nonmatching_file_mode).described_as(
                "remaining file does not preserve the distinctive source mode"
            ).is_not_equal_to(600)
            assert_that(nonmatching_dir_mode).described_as(
                "remaining directory does not preserve the distinctive source mode"
            ).is_not_equal_to(700)
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Build reporting can expose more diagnostic detail or reduce\n"
            "output while retaining task output and failures in silent mode.\n"
            "\n"
            "Corpus obligation: pkg:ant/build-reporting\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_build_reporting(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/build-reporting."""
        log.info("Verifying obligation pkg:ant/build-reporting")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-build-reporting-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            build_file = scratch / "build.xml"
            node.tools[Tee].write_to_file(
                (
                    '<project name="reporting" default="report">\n'
                    '  <target name="report">\n'
                    '    <echo level="info">ORDINARY_LOG_MARKER</echo>\n'
                    '    <echo level="warning">TASK_OUTPUT_MARKER</echo>\n'
                    "  </target>\n"
                    '  <target name="fail">\n'
                    '    <fail message="BUILD_FAILURE_MARKER"/>\n'
                    "  </target>\n"
                    "</project>"
                ),
                build_file,
            )
            verbose_result = node.execute(
                "ant -verbose report",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message="verbose reporting build failed",
            )
            verbose_output = verbose_result.stdout + verbose_result.stderr
            assert_that(verbose_output).described_as(
                "verbose reporting exposes additional build detail"
            ).contains("Buildfile:")
            assert_that(verbose_output).described_as(
                "verbose reporting emits ordinary logging"
            ).contains("ORDINARY_LOG_MARKER")
            silent_result = node.execute(
                "ant -silent report",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message="silent reporting build failed",
            )
            silent_output = silent_result.stdout + silent_result.stderr
            assert_that(silent_output).described_as(
                "silent reporting suppresses ordinary logging"
            ).does_not_contain("ORDINARY_LOG_MARKER")
            assert_that(silent_output).described_as(
                "silent reporting retains task output"
            ).contains("TASK_OUTPUT_MARKER")
            failure_result = node.execute(
                "ant -silent fail",
                cwd=scratch,
                expected_exit_code=1,
                expected_exit_code_failure_message=(
                    "silent reporting did not preserve build failure status"
                ),
            )
            failure_output = failure_result.stdout + failure_result.stderr
            assert_that(failure_output).described_as(
                "silent reporting retains build failures"
            ).contains("BUILD_FAILURE_MARKER")
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Conditions can set a property, and target execution can depend\n"
            "on whether that property is present.\n"
            "\n"
            "Corpus obligation: pkg:ant/conditional-flow\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_conditional_flow(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/conditional-flow."""
        log.info("Verifying obligation pkg:ant/conditional-flow")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-conditional-flow-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            buildfile = scratch / "build.xml"
            node.tools[Tee].write_to_file(
                (
                    '<project name="conditional-flow" default="dispatch">\n'
                    '  <condition property="feature.enabled">\n'
                    '    <equals arg1="${mode}" arg2="enabled"/>\n'
                    "  </condition>\n"
                    '  <target name="dispatch" depends="present,absent"/>\n'
                    '  <target name="present" if="feature.enabled">\n'
                    "    <echo>CONDITION_PRESENT</echo>\n"
                    "  </target>\n"
                    '  <target name="absent" unless="feature.enabled">\n'
                    "    <echo>CONDITION_ABSENT</echo>\n"
                    "  </target>\n"
                    "</project>"
                ),
                buildfile,
                append=False,
                sudo=False,
            )
            satisfied = node.execute(
                "ant -Dmode=enabled",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant build with the condition satisfied should succeed"
                ),
            )
            satisfied_output = satisfied.stdout + satisfied.stderr
            assert_that(satisfied_output).described_as(
                "presence-based target runs when the condition sets its property"
            ).contains("CONDITION_PRESENT")
            assert_that(satisfied_output).described_as(
                "absence-based target is skipped when the property is present"
            ).does_not_contain("CONDITION_ABSENT")

            unsatisfied = node.execute(
                "ant -Dmode=disabled",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant build with the condition unsatisfied should succeed"
                ),
            )
            unsatisfied_output = unsatisfied.stdout + unsatisfied.stderr
            assert_that(unsatisfied_output).described_as(
                "absence-based target runs when the condition leaves its property unset"
            ).contains("CONDITION_ABSENT")
            assert_that(unsatisfied_output).described_as(
                "presence-based target is skipped when the property remains unset"
            ).does_not_contain("CONDITION_PRESENT")
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Filtering changes configured tokens in copied text without\n"
            "consuming tokens that have no associated filter.\n"
            "\n"
            "Corpus obligation: pkg:ant/copy-resources/filtered-text\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_copy_resources_filtered_text(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/copy-resources/filtered-text."""
        log.info("Verifying obligation pkg:ant/copy-resources/filtered-text")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-filtered-text-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            configured = scratch / "configured.txt"
            unconfigured = scratch / "unconfigured.txt"
            buildfile = scratch / "build.xml"
            configured_output = scratch / "configured.out"
            unconfigured_output = scratch / "unconfigured.out"
            node.tools[Tee].write_to_file("value=@configured@", configured)
            node.tools[Tee].write_to_file("value=@unconfigured@", unconfigured)
            node.tools[Tee].write_to_file(
                (
                    '<project name="filtered-copy" default="copy-text">\n'
                    '  <target name="copy-text">\n'
                    '    <copy file="configured.txt" '
                    'tofile="configured.out" filtering="true">\n'
                    "      <filterset>\n"
                    '        <filter token="configured" '
                    'value="expanded"/>\n'
                    "      </filterset>\n"
                    "    </copy>\n"
                    '    <copy file="unconfigured.txt" '
                    'tofile="unconfigured.out" filtering="true">\n'
                    "      <filterset>\n"
                    '        <filter token="configured" '
                    'value="expanded"/>\n'
                    "      </filterset>\n"
                    "    </copy>\n"
                    "  </target>\n"
                    "</project>"
                ),
                buildfile,
            )
            node.execute(
                "ant -f build.xml",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed while filtering configured and unconfigured text"
                ),
            )
            configured_copy = node.tools[Cat].read(str(configured_output))
            unconfigured_copy = node.tools[Cat].read(str(unconfigured_output))
            assert_that(configured_copy).described_as(
                "configured token is expanded in copied text"
            ).contains("value=expanded")
            assert_that(configured_copy).described_as(
                "configured token is consumed by filtering"
            ).does_not_contain("@configured@")
            assert_that(unconfigured_copy).described_as(
                "token without an associated filter remains unchanged"
            ).contains("value=@unconfigured@")
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "A requested target can rely on prerequisite targets without\n"
            "duplicating work along shared dependency chains.\n"
            "\n"
            "Corpus obligation: pkg:ant/dependency-order\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_dependency_order(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/dependency-order."""
        log.info("Verifying obligation pkg:ant/dependency-order")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-dependency-order-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            buildfile = scratch / "build.xml"
            node.tools[Tee].write_to_file(
                (
                    '<project name="dependency-order" default="requested">\n'
                    '  <target name="shared">\n'
                    "    <echo>SHARED_MARKER</echo>\n"
                    "  </target>\n"
                    '  <target name="left" depends="shared">\n'
                    "    <echo>LEFT_MARKER</echo>\n"
                    "  </target>\n"
                    '  <target name="right" depends="shared">\n'
                    "    <echo>RIGHT_MARKER</echo>\n"
                    "  </target>\n"
                    '  <target name="requested" depends="left,right">\n'
                    "    <echo>REQUESTED_MARKER</echo>\n"
                    "  </target>\n"
                    "</project>"
                ),
                buildfile,
            )
            with_dependency = node.execute(
                "ant -f build.xml requested",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant should run the requested target with its dependencies"
                ),
            )
            with_output = with_dependency.stdout + with_dependency.stderr
            shared_position = with_output.find("SHARED_MARKER")
            left_position = with_output.find("LEFT_MARKER")
            right_position = with_output.find("RIGHT_MARKER")
            requested_position = with_output.find("REQUESTED_MARKER")
            (
                assert_that(shared_position)
                .described_as("shared prerequisite runs before the left prerequisite")
                .is_greater_than_or_equal_to(0)
            )
            (
                assert_that(left_position)
                .described_as("left prerequisite runs after the shared prerequisite")
                .is_greater_than(shared_position)
            )
            (
                assert_that(right_position)
                .described_as("right prerequisite runs after the left prerequisite")
                .is_greater_than(left_position)
            )
            (
                assert_that(requested_position)
                .described_as("requested target runs after both prerequisites")
                .is_greater_than(right_position)
            )
            (
                assert_that(with_output[shared_position + len("SHARED_MARKER") :])
                .described_as(
                    "shared prerequisite runs once despite two dependency paths"
                )
                .does_not_contain("SHARED_MARKER")
            )
            (
                assert_that(with_output[left_position + len("LEFT_MARKER") :])
                .described_as("left prerequisite runs only once")
                .does_not_contain("LEFT_MARKER")
            )
            (
                assert_that(with_output[right_position + len("RIGHT_MARKER") :])
                .described_as("right prerequisite runs only once")
                .does_not_contain("RIGHT_MARKER")
            )
            (
                assert_that(with_output[requested_position + len("REQUESTED_MARKER") :])
                .described_as("requested target runs only once")
                .does_not_contain("REQUESTED_MARKER")
            )
            node.tools[Tee].write_to_file(
                (
                    '<project name="dependency-order" default="requested">\n'
                    '  <target name="shared">\n'
                    "    <echo>SHARED_MARKER</echo>\n"
                    "  </target>\n"
                    '  <target name="left" depends="shared">\n'
                    "    <echo>LEFT_MARKER</echo>\n"
                    "  </target>\n"
                    '  <target name="right" depends="shared">\n'
                    "    <echo>RIGHT_MARKER</echo>\n"
                    "  </target>\n"
                    '  <target name="requested" depends="right">\n'
                    "    <echo>REQUESTED_MARKER</echo>\n"
                    "  </target>\n"
                    "</project>"
                ),
                buildfile,
            )
            without_dependency = node.execute(
                "ant -f build.xml requested",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant should run the target after its dependency is removed"
                ),
            )
            without_output = without_dependency.stdout + without_dependency.stderr
            shared_position = without_output.find("SHARED_MARKER")
            right_position = without_output.find("RIGHT_MARKER")
            requested_position = without_output.find("REQUESTED_MARKER")
            (
                assert_that(shared_position)
                .described_as("remaining shared prerequisite still runs")
                .is_greater_than_or_equal_to(0)
            )
            (
                assert_that(right_position)
                .described_as("remaining prerequisite follows its dependency")
                .is_greater_than(shared_position)
            )
            (
                assert_that(requested_position)
                .described_as("requested target follows its remaining prerequisite")
                .is_greater_than(right_position)
            )
            (
                assert_that(without_output)
                .described_as(
                    "removed prerequisite is no longer in the dependency chain"
                )
                .does_not_contain("LEFT_MARKER")
            )
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Directory preparation creates missing parent directories and\n"
            "tolerates an already prepared destination.\n"
            "\n"
            "Corpus obligation: pkg:ant/directory-preparation\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_directory_preparation(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/directory-preparation."""
        log.info("Verifying obligation pkg:ant/directory-preparation")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-directory-preparation-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            buildfile = scratch / "build.xml"
            requested_parent = scratch / "prepared"
            requested = requested_parent / "nested" / "destination"
            node.tools[Tee].write_to_file(
                (
                    '<project name="directory-preparation" '
                    'default="prepare">\n'
                    '  <target name="prepare">\n'
                    '    <mkdir dir="prepared/nested/destination"/>\n'
                    "  </target>\n"
                    '  <target name="other"/>\n'
                    "</project>"
                ),
                buildfile,
                append=False,
                sudo=False,
            )
            assert_that(node.tools[Ls].path_exists(str(requested_parent))).described_as(
                "requested parent tree is absent before the first Ant run"
            ).is_false()
            node.execute(
                "ant prepare",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant should create the missing requested directory tree"
                ),
            )
            assert_that(
                node.tools[Ls].path_exists(str(requested_parent), sudo=False)
            ).described_as(
                "first Ant run creates the missing parent directory"
            ).is_true()
            assert_that(
                node.tools[Ls].path_exists(str(requested), sudo=False)
            ).described_as(
                "first Ant run creates the requested nested directory"
            ).is_true()
            marker = requested / "existing-marker"
            node.tools[Tee].write_to_file(
                "existing destination marker",
                marker,
                append=False,
                sudo=False,
            )
            node.execute(
                "ant prepare",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant should tolerate the already prepared destination"
                ),
            )
            assert_that(
                node.tools[Ls].path_exists(str(requested), sudo=False)
            ).described_as(
                "second Ant run leaves the existing destination in place"
            ).is_true()
            assert_that(node.tools[Cat].read(str(marker), force_run=True)).described_as(
                "second Ant run does not recreate the existing destination"
            ).contains("existing destination marker")
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "A build can turn the presence or absence of a required property\n"
            "into an explicit diagnostic failure.\n"
            "\n"
            "Corpus obligation: pkg:ant/failure-handling/deliberate-diagnostic\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_failure_handling_deliberate_diagnostic(
        self, node: Node, log: Logger
    ) -> None:
        """Verify obligation pkg:ant/failure-handling/deliberate-diagnostic."""
        log.info("Verifying obligation pkg:ant/failure-handling/deliberate-diagnostic")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-deliberate-diagnostic-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            build_file = scratch / "build.xml"
            build_xml = (
                '<project name="diagnostic-test" default="guarded">\n'
                '  <target name="always-fails">\n'
                '    <fail message="UNCONDITIONAL_FAILURE"/>\n'
                "  </target>\n"
                '  <target name="guarded">\n'
                '    <fail if="required.present" status="23" '
                'message="REQUIRED_PROPERTY_PRESENT"/>\n'
                '    <echo message="GUARD_PASSED"/>\n'
                "  </target>\n"
                "</project>"
            )
            node.tools[Tee].write_to_file(
                build_xml,
                build_file,
                append=False,
                sudo=False,
            )

            failed = node.execute(
                "ant -f build.xml -Drequired.present=true guarded",
                cwd=scratch,
                expected_exit_code=23,
                expected_exit_code_failure_message=(
                    "property-present build did not return selected status"
                ),
            )
            failed_output = f"{failed.stdout}\n{failed.stderr}"
            assert_that(failed_output).described_as(
                "satisfied condition emits the configured diagnostic"
            ).contains("REQUIRED_PROPERTY_PRESENT")
            assert_that(failed_output).described_as(
                "satisfied condition halts the current target"
            ).does_not_contain("GUARD_PASSED")

            successful = node.execute(
                "ant -f build.xml guarded",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "property-absent build was halted by the gated fail task"
                ),
            )
            successful_output = f"{successful.stdout}\n{successful.stderr}"
            assert_that(successful_output).described_as(
                "unsatisfied condition allows the target to continue"
            ).contains("GUARD_PASSED")
            assert_that(successful_output).described_as(
                "unsatisfied condition does not emit the failure diagnostic"
            ).does_not_contain("REQUIRED_PROPERTY_PRESENT")
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Keep-going behavior distinguishes independent work from targets\n"
            "blocked by a failed dependency.\n"
            "\n"
            "Corpus obligation: pkg:ant/failure-handling/keep-going\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_failure_handling_keep_going(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/failure-handling/keep-going."""
        log.info("Verifying obligation pkg:ant/failure-handling/keep-going")
        workdir = node.get_pure_path(f"/tmp/lisa-ant-keep-going-{node.name}")
        node.tools[Mkdir].create_directory(str(workdir))
        try:
            build_file = workdir / "build.xml"
            build_xml = (
                '<project name="keep-going" default="requested">\n'
                '  <target name="fail">\n'
                '    <condition property="deliberate.failure">\n'
                '      <equals arg1="enabled" arg2="enabled"/>\n'
                "    </condition>\n"
                '    <fail if="deliberate.failure" message="FAIL_MARKER"/>\n'
                "  </target>\n"
                '  <target name="independent">\n'
                '    <echo message="INDEPENDENT_MARKER"/>\n'
                "  </target>\n"
                '  <target name="blocked" depends="fail">\n'
                '    <echo message="BLOCKED_MARKER"/>\n'
                "  </target>\n"
                '  <target name="requested" '
                'depends="fail,independent,blocked"/>\n'
                "</project>\n"
            )
            node.tools[Tee].write_to_file(build_xml, build_file)

            normal = node.execute(
                "ant -f build.xml requested",
                cwd=workdir,
                expected_exit_code=1,
                expected_exit_code_failure_message=(
                    "Ant without keep-going should report the deliberate failure"
                ),
            )
            normal_output = normal.stdout + normal.stderr
            assert_that(normal_output).described_as(
                "normal mode reaches the deliberate failing target"
            ).contains("FAIL_MARKER")
            assert_that(normal_output).described_as(
                "normal mode stops before the independent target"
            ).does_not_contain("INDEPENDENT_MARKER")
            assert_that(normal_output).described_as(
                "normal mode does not run the target blocked by the failure"
            ).does_not_contain("BLOCKED_MARKER")

            keep_going = node.execute(
                "ant -k -f build.xml requested",
                cwd=workdir,
                expected_exit_code=1,
                expected_exit_code_failure_message=(
                    "Ant keep-going should retain the deliberate build failure"
                ),
            )
            keep_output = keep_going.stdout + keep_going.stderr
            assert_that(keep_output).described_as(
                "keep-going mode still observes the deliberate failure"
            ).contains("FAIL_MARKER")
            assert_that(keep_output).described_as(
                "keep-going mode executes work independent of the failure"
            ).contains("INDEPENDENT_MARKER")
            assert_that(keep_output).described_as(
                "keep-going mode skips the target blocked by the failed dependency"
            ).does_not_contain("BLOCKED_MARKER")
        finally:
            node.tools[Rm].remove_directory(str(workdir))

    @TestCaseMetadata(
        description=(
            "Java compilation selects source files according to corresponding\n"
            "class-file presence and timestamps.\n"
            "\n"
            "Corpus obligation: pkg:ant/incremental-compilation\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_incremental_compilation(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/incremental-compilation."""
        log.info("Verifying obligation pkg:ant/incremental-compilation")
        workdir = node.get_pure_path(
            f"/tmp/lisa-ant-incremental-compilation-{node.name}"
        )
        node.tools[Mkdir].create_directory(str(workdir))
        try:
            srcdir = workdir / "src"
            classdir = workdir / "classes"
            build_file = workdir / "build.xml"
            selected_missing = srcdir / "SelectedMissing.java"
            selected_newer = srcdir / "SelectedNewer.java"
            selected_current = srcdir / "SelectedCurrent.java"
            selected_excluded = srcdir / "SelectedExcluded.java"
            outside_include = srcdir / "Outside.java"
            excluded_class = classdir / "SelectedExcluded.class"
            outside_class = classdir / "Outside.class"
            node.tools[Mkdir].create_directory(str(srcdir))
            node.tools[Mkdir].create_directory(str(classdir))
            node.tools[Tee].write_to_file(
                (
                    '<project name="incremental" default="compile">\n'
                    '  <target name="seed">\n'
                    '    <javac srcdir="src" destdir="classes" '
                    'includeantruntime="false">\n'
                    '      <include name="SelectedNewer.java"/>\n'
                    '      <include name="SelectedCurrent.java"/>\n'
                    "    </javac>\n"
                    "  </target>\n"
                    '  <target name="newer">\n'
                    '    <touch file="src/SelectedNewer.java" '
                    'millis="1893456000000"/>\n'
                    '    <touch file="src/SelectedCurrent.java" '
                    'millis="946684800000"/>\n'
                    "  </target>\n"
                    '  <target name="settle">\n'
                    '    <touch file="src/SelectedMissing.java" '
                    'millis="946684800000"/>\n'
                    '    <touch file="src/SelectedNewer.java" '
                    'millis="946684800000"/>\n'
                    '    <touch file="src/SelectedCurrent.java" '
                    'millis="946684800000"/>\n'
                    "  </target>\n"
                    '  <target name="compile">\n'
                    '    <javac srcdir="src" destdir="classes" '
                    'includeantruntime="false">\n'
                    '      <include name="Selected*.java"/>\n'
                    '      <exclude name="SelectedExcluded.java"/>\n'
                    "    </javac>\n"
                    "  </target>\n"
                    "</project>"
                ),
                build_file,
            )
            node.tools[Tee].write_to_file(
                (
                    "public class SelectedMissing {\n"
                    "  public static void main(String[] args) {\n"
                    '    System.out.println("ALPHA");\n'
                    "  }\n"
                    "}"
                ),
                selected_missing,
            )
            node.tools[Tee].write_to_file(
                (
                    "public class SelectedNewer {\n"
                    "  public static void main(String[] args) {\n"
                    '    System.out.println("DELTA");\n'
                    "  }\n"
                    "}"
                ),
                selected_newer,
            )
            node.tools[Tee].write_to_file(
                (
                    "public class SelectedCurrent {\n"
                    "  public static void main(String[] args) {\n"
                    '    System.out.println("CHARLIE");\n'
                    "  }\n"
                    "}"
                ),
                selected_current,
            )
            node.tools[Tee].write_to_file(
                "not valid java for excluded input",
                selected_excluded,
            )
            node.tools[Tee].write_to_file(
                "not valid java outside the include pattern",
                outside_include,
            )
            node.execute(
                "ant seed",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message="Ant could not seed classes",
            )
            node.tools[Tee].write_to_file(
                (
                    "public class SelectedNewer {\n"
                    "  public static void main(String[] args) {\n"
                    '    System.out.println("BRAVO");\n'
                    "  }\n"
                    "}"
                ),
                selected_newer,
            )
            node.tools[Tee].write_to_file(
                "not valid java for a current source",
                selected_current,
            )
            node.execute(
                "ant newer",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message="Ant could not set source times",
            )
            node.execute(
                "ant compile",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant did not compile selected sources"
                ),
            )
            missing_result = node.execute(
                "java -cp classes SelectedMissing",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message="Missing class was not runnable",
            )
            assert_that(
                f"{missing_result.stdout}\n{missing_result.stderr}"
            ).described_as(
                "a selected source without a class file is compiled"
            ).contains(
                "ALPHA"
            )
            newer_result = node.execute(
                "java -cp classes SelectedNewer",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message="Newer class was not runnable",
            )
            assert_that(f"{newer_result.stdout}\n{newer_result.stderr}").described_as(
                "a selected source newer than its class file is recompiled"
            ).contains("BRAVO")
            current_result = node.execute(
                "java -cp classes SelectedCurrent",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message="Current class was not preserved",
            )
            assert_that(
                f"{current_result.stdout}\n{current_result.stderr}"
            ).described_as(
                "a current corresponding class file is not recompiled"
            ).contains(
                "CHARLIE"
            )
            assert_that(node.tools[Ls].path_exists(str(excluded_class))).described_as(
                "the configured exclude pattern prevents class generation"
            ).is_false()
            assert_that(node.tools[Ls].path_exists(str(outside_class))).described_as(
                "the configured include pattern bounds the selected source set"
            ).is_false()
            node.tools[Tee].write_to_file(
                "not valid java after missing source compilation",
                selected_missing,
            )
            node.tools[Tee].write_to_file(
                "not valid java after newer source compilation",
                selected_newer,
            )
            node.execute(
                "ant settle",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message="Ant could not make classes current",
            )
            node.execute(
                "ant compile",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant recompiled sources with current classes"
                ),
            )
            settled_missing = node.execute(
                "java -cp classes SelectedMissing",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message="Former missing class changed",
            )
            assert_that(
                f"{settled_missing.stdout}\n{settled_missing.stderr}"
            ).described_as(
                "the current class for the formerly missing source is retained"
            ).contains(
                "ALPHA"
            )
            settled_newer = node.execute(
                "java -cp classes SelectedNewer",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message="Former newer class changed",
            )
            assert_that(f"{settled_newer.stdout}\n{settled_newer.stderr}").described_as(
                "the current class for the formerly newer source is retained"
            ).contains("BRAVO")
            settled_current = node.execute(
                "java -cp classes SelectedCurrent",
                cwd=workdir,
                expected_exit_code=0,
                expected_exit_code_failure_message="Seeded current class changed",
            )
            assert_that(
                f"{settled_current.stdout}\n{settled_current.stderr}"
            ).described_as(
                "all current corresponding class files remain usable"
            ).contains(
                "CHARLIE"
            )
        finally:
            node.tools[Rm].remove_directory(str(workdir))

    @TestCaseMetadata(
        description=(
            "A build can run a required system command only on an allowed\n"
            "operating system and provide noninteractive input explicitly.\n"
            "\n"
            "Corpus obligation: pkg:ant/platform-command\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_platform_command(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/platform-command."""
        log.info("Verifying obligation pkg:ant/platform-command")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-platform-command-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            buildfile = scratch / "build.xml"
            build_xml = (
                '<project name="platform-command" default="platform">\n'
                '  <target name="read">\n'
                '    <echo message="reader-started"/>\n'
                '    <input addproperty="received"/>\n'
                '    <echo message="received=${received}"/>\n'
                '    <echo message="reader-completed"/>\n'
                "  </target>\n"
                '  <target name="platform">\n'
                '    <exec executable="ant" osfamily="${allowed.family}" '
                'inputstring="${provided.input}" failonerror="false">\n'
                '      <arg value="-f"/>\n'
                '      <arg value="build.xml"/>\n'
                '      <arg value="read"/>\n'
                "    </exec>\n"
                "  </target>\n"
                '  <target name="eof">\n'
                '    <exec executable="ant" osfamily="unix" '
                'failonerror="false">\n'
                '      <arg value="-f"/>\n'
                '      <arg value="build.xml"/>\n'
                '      <arg value="read"/>\n'
                "    </exec>\n"
                "  </target>\n"
                "</project>"
            )
            node.tools[Tee].write_to_file(build_xml, buildfile)
            supplied = node.execute(
                (
                    "ant -f build.xml -Dallowed.family=unix "
                    "-Dprovided.input=supplied-data platform"
                ),
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant should run the command on the matching operating system"
                ),
            )
            supplied_output = supplied.stdout + supplied.stderr
            assert_that(supplied_output).described_as(
                "matching operating system starts the configured command"
            ).contains("reader-started")
            assert_that(supplied_output).described_as(
                "explicit task input is available to the configured command"
            ).contains("received=supplied-data")
            assert_that(supplied_output).described_as(
                "the command completes after consuming explicit task input"
            ).contains("reader-completed")
            blocked = node.execute(
                (
                    "ant -f build.xml -Dallowed.family=windows "
                    "-Dprovided.input=blocked-data platform"
                ),
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant should skip the command on a nonmatching operating system"
                ),
            )
            blocked_output = blocked.stdout + blocked.stderr
            assert_that(blocked_output).described_as(
                "nonmatching operating system does not start the command"
            ).does_not_contain("reader-started")
            assert_that(blocked_output).described_as(
                "a skipped command cannot consume its configured input"
            ).does_not_contain("received=blocked-data")
            eof = node.execute(
                "ant -f build.xml eof",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant should finish after the child receives end of file"
                ),
            )
            eof_output = eof.stdout + eof.stderr
            assert_that(eof_output).described_as(
                "the command starts before attempting interactive input"
            ).contains("reader-started")
            assert_that(eof_output).described_as(
                "interactive input reaches end of file instead of completing"
            ).does_not_contain("reader-completed")
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Path-like build values remain usable across operating systems\n"
            "when written with either documented separator.\n"
            "\n"
            "Corpus obligation: pkg:ant/portable-paths\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_portable_paths(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/portable-paths."""
        log.info("Verifying obligation pkg:ant/portable-paths")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-portable-paths-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            alpha = scratch / "alpha"
            beta = scratch / "beta"
            build_file = scratch / "build.xml"
            node.tools[Mkdir].create_directory(str(alpha))
            node.tools[Mkdir].create_directory(str(beta))
            colon_build = (
                '<project name="portable-paths" default="show">\n'
                '  <target name="show">\n'
                '    <path id="portable.reference" path="alpha:beta"/>\n'
                '    <property name="portable.value" '
                'refid="portable.reference"/>\n'
                '    <echo message="PORTABLE=${portable.value}"/>\n'
                "  </target>\n"
                "</project>"
            )
            node.tools[Tee].write_to_file(
                colon_build,
                build_file,
                append=False,
                sudo=False,
            )
            colon_result = node.execute(
                "ant -f build.xml",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed for the colon-separated path"
                ),
            )
            semicolon_build = (
                '<project name="portable-paths" default="show">\n'
                '  <target name="show">\n'
                '    <path id="portable.reference" path="alpha;beta"/>\n'
                '    <property name="portable.value" '
                'refid="portable.reference"/>\n'
                '    <echo message="PORTABLE=${portable.value}"/>\n'
                "  </target>\n"
                "</project>"
            )
            node.tools[Tee].write_to_file(
                semicolon_build,
                build_file,
                append=False,
                sudo=False,
            )
            semicolon_result = node.execute(
                "ant -f build.xml",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant failed for the semicolon-separated path"
                ),
            )
            colon_output = f"{colon_result.stdout}\n{colon_result.stderr}"
            semicolon_output = f"{semicolon_result.stdout}\n{semicolon_result.stderr}"
            colon_lines = [
                line for line in colon_output.splitlines() if "PORTABLE=" in line
            ]
            semicolon_lines = [
                line for line in semicolon_output.splitlines() if "PORTABLE=" in line
            ]
            assert_that(colon_lines).described_as(
                "colon form emits one resolved path-like value"
            ).is_length(1)
            assert_that(semicolon_lines).described_as(
                "semicolon form emits one resolved path-like value"
            ).is_length(1)
            colon_value = colon_lines[0].split("PORTABLE=", 1)[1].strip()
            semicolon_value = semicolon_lines[0].split("PORTABLE=", 1)[1].strip()
            expected_value = f"{alpha}:{beta}"
            assert_that(colon_value).described_as(
                "colon input uses the operating system path separator"
            ).is_equal_to(expected_value)
            assert_that(semicolon_value).described_as(
                "semicolon input converts to the operating system path separator"
            ).is_equal_to(expected_value)
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Named properties provide case-sensitive substitutions across\n"
            "subsequent tasks and targets, while command-line values take\n"
            "precedence over values in the buildfile.\n"
            "\n"
            "Corpus obligation: pkg:ant/property-customization\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_property_customization(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/property-customization."""
        log.info("Verifying obligation pkg:ant/property-customization")
        scratch = node.get_pure_path(
            f"/tmp/lisa-ant-property-customization-{node.name}"
        )
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            buildfile = scratch / "build.xml"
            build_text = (
                '<project name="property-test" default="later">\n'
                '  <property name="Greeting" value="build-value"/>\n'
                '  <property name="greeting" value="lower-value"/>\n'
                '  <target name="first">\n'
                "    <echo>first-upper:${Greeting}</echo>\n"
                "    <echo>first-lower:${greeting}</echo>\n"
                '    <property name="Greeting" value="late-value"/>\n'
                "    <echo>after-upper:${Greeting}</echo>\n"
                "  </target>\n"
                '  <target name="later" depends="first">\n'
                "    <echo>later-upper:${Greeting}</echo>\n"
                "    <echo>later-lower:${greeting}</echo>\n"
                "  </target>\n"
                "</project>"
            )
            node.tools[Tee].write_to_file(
                build_text, buildfile, append=False, sudo=False
            )
            first = node.execute(
                "ant -f build.xml",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=("Ant buildfile-value run failed"),
            )
            first_output = f"{first.stdout}\n{first.stderr}"
            assert_that(first_output).described_as(
                "buildfile property expands in the first task"
            ).contains("first-upper:build-value")
            assert_that(first_output).described_as(
                "property names remain case-sensitive in the first run"
            ).contains("first-lower:lower-value")
            assert_that(first_output).described_as(
                "buildfile property resists redefinition in a later task"
            ).contains("after-upper:build-value")
            assert_that(first_output).described_as(
                "buildfile property remains selected in a later target"
            ).contains("later-upper:build-value")
            assert_that(first_output).described_as(
                "lowercase property remains distinct in a later target"
            ).contains("later-lower:lower-value")
            second = node.execute(
                "ant -f build.xml -DGreeting=command-value",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant command-line-value run failed"
                ),
            )
            second_output = f"{second.stdout}\n{second.stderr}"
            assert_that(second_output).described_as(
                "command-line property overrides the buildfile value"
            ).contains("first-upper:command-value")
            assert_that(second_output).described_as(
                "command-line property name matching is case-sensitive"
            ).contains("first-lower:lower-value")
            assert_that(second_output).described_as(
                "command-line property resists later task redefinition"
            ).contains("after-upper:command-value")
            assert_that(second_output).described_as(
                "command-line property remains selected in a later target"
            ).contains("later-upper:command-value")
            assert_that(second_output).described_as(
                "distinct lowercase property remains unchanged"
            ).contains("later-lower:lower-value")
        finally:
            node.tools[Rm].remove_directory(str(scratch))

    @TestCaseMetadata(
        description=(
            "Cleanup removes the selected file, link, directory tree, or\n"
            "resources while preserving material outside the selection.\n"
            "\n"
            "Corpus obligation: pkg:ant/selected-removal\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        timeout=120,
        requirement=simple_requirement(supported_os=[CBLMariner]),
    )
    def verify_selected_removal(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/selected-removal."""
        log.info("Verifying obligation pkg:ant/selected-removal")
        scratch = node.get_pure_path(f"/tmp/lisa-ant-selected-removal-{node.name}")
        node.tools[Mkdir].create_directory(str(scratch))
        try:
            selected = scratch / "selected.tmp"
            outside = scratch / "outside.keep"
            empty_selected = scratch / "empty-selected"
            buildfile = scratch / "build.xml"
            node.tools[Mkdir].create_directory(str(empty_selected))
            node.tools[Tee].write_to_file("selected payload", selected)
            node.tools[Tee].write_to_file("outside payload", outside)
            node.tools[Tee].write_to_file(
                (
                    '<project name="selected-removal" default="cleanup">\n'
                    '  <target name="cleanup">\n'
                    '    <delete includeEmptyDirs="true">\n'
                    '      <fileset dir=".">\n'
                    '        <include name="selected.tmp"/>\n'
                    '        <include name="empty-selected/**"/>\n'
                    "      </fileset>\n"
                    "    </delete>\n"
                    "  </target>\n"
                    '  <target name="other"/>\n'
                    "</project>"
                ),
                buildfile,
            )
            node.execute(
                "ant cleanup",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant cleanup should remove selected files and requested empty "
                    "directories"
                ),
            )
            assert_that(node.tools[Ls].path_exists(str(selected))).described_as(
                "cleanup removes the selected file"
            ).is_false()
            assert_that(node.tools[Ls].path_exists(str(empty_selected))).described_as(
                "cleanup removes selected empty directories when requested"
            ).is_false()
            assert_that(node.tools[Ls].path_exists(str(outside))).described_as(
                "cleanup preserves resources outside the selection"
            ).is_true()
            node.tools[Tee].write_to_file("changed outside payload", outside)
            node.execute(
                "ant cleanup",
                cwd=scratch,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Ant cleanup should succeed after the changed resource remains "
                    "outside the selection"
                ),
            )
            assert_that(node.tools[Ls].path_exists(str(outside))).described_as(
                "cleanup preserves the changed resource outside the selection"
            ).is_true()
            preserved = node.tools[Cat].read(str(outside), force_run=True)
            assert_that(preserved).described_as(
                "cleanup leaves changed outside-resource content intact"
            ).contains("changed outside payload")
        finally:
            node.tools[Rm].remove_directory(str(scratch))
