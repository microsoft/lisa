# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Release-gate tests for ant on Azure Linux.

Each case verifies one reviewed behaviour obligation directly against the
node under test. Generated from a reviewed behaviour corpus (IR).
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
from lisa.tools import Cat, Chmod, Cp, Find, Mkdir, Rm, Stat, Tee
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
            "Verifies the ant behaviour: JAR creation remains usable when the\n"
            "user does not supply a manifest or selected files.\n"
            "\n"
            "Corpus obligation: pkg:ant/archive-workflows/jar-manifest\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_archive_workflows_jar_manifest(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/archive-workflows/jar-manifest."""
        log.info("Verifying obligation pkg:ant/archive-workflows/jar-manifest")
        root = node.get_pure_path(f"/tmp/lisa-ant-jar-manifest-{node.name}")
        node.tools[Rm].remove_directory(str(root))
        try:
            input_dir = root / "input"
            build_file = root / "build.xml"
            manifest_file = root / "custom.mf"
            payload_file = input_dir / "payload.txt"
            node.tools[Mkdir].create_directory(str(root))
            node.tools[Mkdir].create_directory(str(input_dir))
            build_xml = (
                '<project name="jar-manifest" default="all">\n'
                '  <target name="supplied">\n'
                '    <jar destfile="supplied.jar" manifest="custom.mf">\n'
                '      <fileset dir="input">\n'
                '        <include name="payload.txt"/>\n'
                "      </fileset>\n"
                "    </jar>\n"
                "  </target>\n"
                '  <target name="defaulted" depends="supplied">\n'
                '    <jar destfile="default.jar">\n'
                '      <fileset dir="input">\n'
                '        <include name="no-match.bin"/>\n'
                "      </fileset>\n"
                "    </jar>\n"
                "  </target>\n"
                '  <target name="all" depends="defaulted"/>\n'
                "</project>"
            )
            manifest = (
                "Manifest-Version: 1.0\nX-Test-Marker: SUPPLIED-MANIFEST-MARKER\n"
            )
            node.tools[Tee].write_to_file(build_xml, build_file)
            node.tools[Tee].write_to_file(manifest, manifest_file)
            node.tools[Tee].write_to_file("SELECTED-PAYLOAD-MARKER", payload_file)

            build = node.execute("ant -f build.xml", cwd=root)
            assert_that(build.exit_code).described_as(
                "Ant creates the supplied-manifest and default-manifest JARs"
            ).is_equal_to(0)

            first_list = node.execute("jar tf supplied.jar", cwd=root)
            first_listing = first_list.stdout + "\n" + first_list.stderr
            first_extract = node.execute(
                "jar xf supplied.jar META-INF/MANIFEST.MF",
                cwd=root,
            )
            assert_that(first_extract.exit_code).described_as(
                "the supplied-manifest JAR remains extractable"
            ).is_equal_to(0)
            extracted_manifest = root / "META-INF" / "MANIFEST.MF"
            first_manifest = node.tools[Cat].read(
                str(extracted_manifest), force_run=True
            )
            assert_that(first_listing).described_as(
                "the supplied-manifest JAR contains the selected file"
            ).contains("payload.txt")
            assert_that(first_manifest).described_as(
                "the first JAR uses the user-supplied manifest"
            ).contains("SUPPLIED-MANIFEST-MARKER")

            node.tools[Rm].remove_directory(str(root / "META-INF"))
            second_list = node.execute("jar tf default.jar", cwd=root)
            second_listing = second_list.stdout + "\n" + second_list.stderr
            second_extract = node.execute(
                "jar xf default.jar META-INF/MANIFEST.MF",
                cwd=root,
            )
            assert_that(second_extract.exit_code).described_as(
                "the no-match default-manifest JAR remains extractable"
            ).is_equal_to(0)
            second_manifest = node.tools[Cat].read(
                str(extracted_manifest), force_run=True
            )
            assert_that(second_listing).described_as(
                "the no-match JAR still contains its generated manifest"
            ).contains("META-INF/MANIFEST.MF")
            assert_that(second_listing).described_as(
                "the no-match JAR does not include the available payload"
            ).does_not_contain("payload.txt")
            assert_that(second_manifest).described_as(
                "Ant supplies a simple manifest when none is configured"
            ).contains("Manifest-Version:")
            assert_that(second_manifest).described_as(
                "the generated manifest does not reuse the supplied manifest"
            ).does_not_contain("SUPPLIED-MANIFEST-MARKER")
        finally:
            node.tools[Rm].remove_directory(str(root))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: ZIP, WAR, and JAR extraction can\n"
            "narrow output through patterns and transform output names\n"
            "through a mapper.\n"
            "\n"
            "Corpus obligation: pkg:ant/archive-workflows/patterned-extraction\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_archive_workflows_patterned_extraction(
        self, node: Node, log: Logger
    ) -> None:
        """Verify obligation pkg:ant/archive-workflows/patterned-extraction."""
        log.info("Verifying obligation pkg:ant/archive-workflows/patterned-extraction")
        workspace = node.get_pure_path("/tmp/lisa-ant-patterned-extraction")
        node.tools[Rm].remove_directory(str(workspace))
        node.tools[Mkdir].create_directory(str(workspace))
        try:
            src_dir = workspace / "src"
            build_path = workspace / "build.xml"
            alpha_path = src_dir / "alpha.txt"
            beta_path = src_dir / "beta.bin"
            all_dir = workspace / "all"
            pattern_dir = workspace / "pattern"
            all_alpha = all_dir / "alpha.txt"
            all_beta = all_dir / "beta.bin"
            pattern_alpha = pattern_dir / "mapped-alpha.out"
            node.tools[Mkdir].create_directory(str(src_dir))
            node.tools[Mkdir].create_directory(str(all_dir))
            node.tools[Mkdir].create_directory(str(pattern_dir))
            buildfile = (
                '<project name="patterned-extraction" default="make-archive">\n'
                '  <target name="make-archive">\n'
                '    <zip destfile="fixture.zip">\n'
                '      <zipfileset dir="src" '
                'includes="alpha.txt,beta.bin" filemode="700"/>\n'
                "    </zip>\n"
                "  </target>\n"
                '  <target name="extract-all">\n'
                '    <unzip src="fixture.zip" dest="all" overwrite="true"/>\n'
                "  </target>\n"
                '  <target name="extract-pattern">\n'
                '    <unzip src="fixture.zip" dest="pattern" '
                'overwrite="true">\n'
                "      <patternset>\n"
                '        <include name="*.txt"/>\n'
                "      </patternset>\n"
                '      <mapper type="glob" from="*.txt" '
                'to="mapped-*.out"/>\n'
                "    </unzip>\n"
                "  </target>\n"
                "</project>"
            )
            node.tools[Tee].write_to_file(buildfile, build_path)
            node.tools[Tee].write_to_file("matching archive member", alpha_path)
            node.tools[Tee].write_to_file("nonmatching archive member", beta_path)
            node.tools[Chmod].chmod(str(alpha_path), "700")
            node.tools[Chmod].chmod(str(beta_path), "700")
            node.tools[Tee].write_to_file("all alpha sentinel", all_alpha)
            node.tools[Tee].write_to_file("all beta sentinel", all_beta)
            node.tools[Tee].write_to_file("pattern alpha sentinel", pattern_alpha)
            node.tools[Chmod].chmod(str(all_alpha), "600")
            node.tools[Chmod].chmod(str(all_beta), "600")
            node.tools[Chmod].chmod(str(pattern_alpha), "600")
            node.execute(
                "ant -f build.xml make-archive",
                cwd=workspace,
                expected_exit_code=0,
            )
            node.execute(
                "ant -f build.xml extract-all",
                cwd=workspace,
                expected_exit_code=0,
            )
            node.execute(
                "ant -f build.xml extract-pattern",
                cwd=workspace,
                expected_exit_code=0,
            )
            all_files = node.tools[Find].find_files(all_dir, file_type="f")
            pattern_files = node.tools[Find].find_files(pattern_dir, file_type="f")
            all_entries = sorted(item.rsplit("/", 1)[-1] for item in all_files)
            pattern_entries = sorted(item.rsplit("/", 1)[-1] for item in pattern_files)
            assert_that(all_entries).described_as(
                "unpatterned extraction contains every archive member"
            ).is_equal_to(["alpha.txt", "beta.bin"])
            assert_that(pattern_entries).described_as(
                "patterned extraction contains only the mapped matching member"
            ).is_equal_to(["mapped-alpha.out"])
            all_alpha_content = node.tools[Cat].read(str(all_alpha))
            all_beta_content = node.tools[Cat].read(str(all_beta))
            pattern_content = node.tools[Cat].read(str(pattern_alpha))
            assert_that(all_alpha_content).described_as(
                "unpatterned extraction replaces the alpha destination content"
            ).contains("matching archive member")
            assert_that(all_beta_content).described_as(
                "unpatterned extraction replaces the beta destination content"
            ).contains("nonmatching archive member")
            assert_that(pattern_content).described_as(
                "mapped extraction replaces the selected destination content"
            ).contains("matching archive member")
            all_permissions = [
                node.tools[Stat].get_file_permission(str(all_alpha)),
                node.tools[Stat].get_file_permission(str(all_beta)),
            ]
            pattern_permission = node.tools[Stat].get_file_permission(
                str(pattern_alpha)
            )
            assert_that(all_permissions).described_as(
                "unpatterned extraction does not restore archived file permissions"
            ).does_not_contain(700)
            assert_that(pattern_permission).described_as(
                "mapped extraction does not restore the archived file permission"
            ).is_not_equal_to(700)
        finally:
            node.tools[Rm].remove_directory(str(workspace))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: ZIP creation uses relative paths\n"
            "from selected filesets and excludes files that do not match the\n"
            "selection.\n"
            "\n"
            "Corpus obligation: pkg:ant/archive-workflows/zip-selection\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_archive_workflows_zip_selection(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/archive-workflows/zip-selection."""
        log.info("Verifying obligation pkg:ant/archive-workflows/zip-selection")
        root = node.get_pure_path("/tmp/lisa-ant-zip-selection")
        node.tools[Rm].remove_directory(path=str(root))
        input_dir = root / "input"
        nested_dir = input_dir / "nested"
        build_file = root / "build.xml"
        source_file = nested_dir / "chosen.keep"
        skipped_file = nested_dir / "chosen.skip"
        anchor_file = nested_dir / "anchor.keep"
        blocked_file = nested_dir / "blocked.keep"
        parser_file = root / "ArchiveMode.java"
        node.tools[Mkdir].create_directory(str(nested_dir))
        build_xml = (
            '<project name="zip-selection" default="archive">\n'
            '  <target name="archive">\n'
            '    <delete file="selected.zip"/>\n'
            '    <zip destfile="selected.zip" basedir="input">\n'
            '      <include name="nested/*.keep"/>\n'
            '      <exclude name="nested/blocked.keep"/>\n'
            "    </zip>\n"
            "  </target>\n"
            "</project>"
        )
        parser_source = (
            "import java.nio.charset.StandardCharsets;\n"
            "import java.nio.file.Files;\n"
            "import java.nio.file.Paths;\n"
            "public class ArchiveMode {\n"
            "    static int u16(byte[] b, int p) {\n"
            "        return (b[p] & 255) | ((b[p + 1] & 255) << 8);\n"
            "    }\n"
            "    static long u32(byte[] b, int p) {\n"
            "        return (u16(b, p) & 65535L)\n"
            "            | ((long) u16(b, p + 2) << 16);\n"
            "    }\n"
            "    public static void main(String[] args) throws Exception {\n"
            '        byte[] b = Files.readAllBytes(Paths.get("selected.zip"));\n'
            "        for (int p = 0; p + 46 <= b.length; p++) {\n"
            "            if (u32(b, p) == 0x02014b50L) {\n"
            "                int n = u16(b, p + 28);\n"
            "                int x = u16(b, p + 30);\n"
            "                int c = u16(b, p + 32);\n"
            "                String name = new String(\n"
            "                    b, p + 46, n, StandardCharsets.UTF_8);\n"
            '                if (name.equals("nested/chosen.keep")) {\n'
            "                    long attrs = u32(b, p + 38);\n"
            "                    int mode = (int) ((attrs >>> 16) & 0777);\n"
            "                    System.out.println(Integer.toOctalString(mode));\n"
            "                    return;\n"
            "                }\n"
            "                p += 45 + n + x + c;\n"
            "            }\n"
            "        }\n"
            '        throw new RuntimeException("entry missing");\n'
            "    }\n"
            "}"
        )
        node.tools[Tee].write_to_file(build_xml, build_file)
        node.tools[Tee].write_to_file("selected payload", source_file)
        node.tools[Tee].write_to_file("stable payload", anchor_file)
        node.tools[Tee].write_to_file("excluded payload", blocked_file)
        node.tools[Tee].write_to_file(parser_source, parser_file)
        node.tools[Chmod].chmod(str(source_file), "600")
        source_mode = node.tools[Stat].get_file_permission(str(source_file))
        node.execute(
            "javac ArchiveMode.java",
            cwd=root,
            expected_exit_code=0,
        )
        node.execute(
            "ant -f build.xml archive",
            cwd=root,
            expected_exit_code=0,
        )
        first_listing = node.execute(
            "jar tf selected.zip",
            cwd=root,
            expected_exit_code=0,
        )
        mode_result = node.execute(
            "java ArchiveMode",
            cwd=root,
            expected_exit_code=0,
        )
        node.tools[Cp].copy(source_file, skipped_file)
        node.tools[Rm].remove_file(str(source_file))
        node.execute(
            "ant -f build.xml archive",
            cwd=root,
            expected_exit_code=0,
        )
        second_listing = node.execute(
            "jar tf selected.zip",
            cwd=root,
            expected_exit_code=0,
        )
        first_text = first_listing.stdout + first_listing.stderr
        second_text = second_listing.stdout + second_listing.stderr
        archive_mode = (mode_result.stdout + mode_result.stderr).strip()
        assert_that(first_text).described_as(
            "matching file is archived at its relative fileset path"
        ).contains("nested/chosen.keep")
        assert_that(first_text).described_as(
            "explicitly excluded file is absent from the archive"
        ).does_not_contain("nested/blocked.keep")
        assert_that(archive_mode).described_as(
            "archive does not preserve the selected source file permissions"
        ).is_not_equal_to(str(source_mode))
        assert_that(second_text).described_as(
            "unchanged selected input remains archived after rebuilding"
        ).contains("nested/anchor.keep")
        assert_that(second_text).described_as(
            "the former selected path is removed when the archive is rebuilt"
        ).does_not_contain("nested/chosen.keep")
        assert_that(second_text).described_as(
            "the changed file is absent when its new path does not match"
        ).does_not_contain("nested/chosen.skip")
        assert_that(second_text).described_as(
            "the exclude rule still omits its matching input after rebuilding"
        ).does_not_contain("nested/blocked.keep")
        node.tools[Rm].remove_directory(str(root))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: Build reporting can expose more\n"
            "diagnostic detail or reduce output while retaining task output\n"
            "and failures in silent mode.\n"
            "\n"
            "Corpus obligation: pkg:ant/build-reporting\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_build_reporting(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/build-reporting."""
        log.info("Verifying obligation pkg:ant/build-reporting")
        work_dir = node.get_pure_path("/tmp/lisa-ant-build-reporting")
        build_file = work_dir / "build.xml"
        build_xml = (
            '<?xml version="1.0"?>\n'
            '<project name="diagnostic_project" '
            'default="ordinary_logging_marker">\n'
            '  <target name="ordinary_logging_marker">\n'
            "    <echo>VISIBLE_TASK_OUTPUT</echo>\n"
            '    <fail message="VISIBLE_BUILD_FAILURE"/>\n'
            "  </target>\n"
            "</project>"
        )
        node.tools[Rm].remove_directory(str(work_dir))
        node.tools[Mkdir].create_directory(str(work_dir))
        try:
            node.tools[Tee].write_to_file(build_xml, build_file)
            verbose = node.execute(
                "ant -verbose -f build.xml",
                cwd=work_dir,
            )
            silent = node.execute(
                "ant -silent -f build.xml",
                cwd=work_dir,
            )
            verbose_text = f"{verbose.stdout}\n{verbose.stderr}"
            silent_text = f"{silent.stdout}\n{silent.stderr}"
            assert_that(verbose.exit_code).described_as(
                "verbose build reports the arranged build failure"
            ).is_not_equal_to(0)
            assert_that(verbose_text).described_as(
                "verbose reporting exposes additional target detail"
            ).contains("ordinary_logging_marker")
            assert_that(verbose_text).described_as(
                "verbose reporting retains task output"
            ).contains("VISIBLE_TASK_OUTPUT")
            assert_that(silent.exit_code).described_as(
                "silent mode retains build failure status"
            ).is_not_equal_to(0)
            assert_that(silent_text).described_as(
                "silent mode suppresses ordinary target logging"
            ).does_not_contain("ordinary_logging_marker")
            assert_that(silent_text).described_as(
                "silent mode retains task output"
            ).contains("VISIBLE_TASK_OUTPUT")
            assert_that(silent_text).described_as(
                "silent mode emits the build failure"
            ).contains("VISIBLE_BUILD_FAILURE")
        finally:
            node.tools[Rm].remove_directory(str(work_dir))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: Conditions can set a property, and\n"
            "target execution can depend on whether that property is present.\n"
            "\n"
            "Corpus obligation: pkg:ant/conditional-flow\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_conditional_flow(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/conditional-flow."""
        log.info("Verifying obligation pkg:ant/conditional-flow")
        work_dir = node.get_pure_path(f"/tmp/lisa-ant-flow-{id(node)}")
        build_file = work_dir / "build.xml"
        node.tools[Mkdir].create_directory(str(work_dir))
        try:
            build_xml = (
                '<project name="conditional-flow" default="verify">\n'
                '  <target name="decide">\n'
                '    <condition property="flow.enabled" '
                'value="FLOW_ENABLED_VALUE">\n'
                '      <equals arg1="${condition.input}" arg2="yes"/>\n'
                "    </condition>\n"
                "  </target>\n"
                '  <target name="presence" depends="decide" '
                'if="flow.enabled">\n'
                '    <echo message="FLOW_PROPERTY=${flow.enabled}"/>\n'
                '    <echo message="PRESENCE_BRANCH_EXECUTED"/>\n'
                "  </target>\n"
                '  <target name="absence" depends="decide" '
                'unless="flow.enabled">\n'
                '    <echo message="ABSENCE_BRANCH_EXECUTED"/>\n'
                "  </target>\n"
                '  <target name="verify" depends="presence,absence"/>\n'
                "</project>"
            )
            node.tools[Tee].write_to_file(build_xml, build_file)

            positive = node.execute(
                "ant -f build.xml -Dcondition.input=yes",
                shell=False,
                cwd=work_dir,
            )
            positive_output = positive.stdout + positive.stderr
            assert_that(positive.exit_code).described_as(
                "build succeeds when the condition is satisfied"
            ).is_equal_to(0)
            assert_that(positive_output).described_as(
                "satisfied condition sets the named property"
            ).contains("FLOW_PROPERTY=FLOW_ENABLED_VALUE")
            assert_that(positive_output).described_as(
                "presence-based target runs when the property is set"
            ).contains("PRESENCE_BRANCH_EXECUTED")
            assert_that(positive_output).described_as(
                "absence-based target is skipped when the property is set"
            ).does_not_contain("ABSENCE_BRANCH_EXECUTED")

            negative = node.execute(
                "ant -f build.xml -Dcondition.input=no",
                shell=False,
                cwd=work_dir,
            )
            negative_output = negative.stdout + negative.stderr
            assert_that(negative.exit_code).described_as(
                "build succeeds when the condition is not satisfied"
            ).is_equal_to(0)
            assert_that(negative_output).described_as(
                "absence-based target runs while the property remains unset"
            ).contains("ABSENCE_BRANCH_EXECUTED")
            assert_that(negative_output).described_as(
                "presence-based target is skipped while the property is unset"
            ).does_not_contain("PRESENCE_BRANCH_EXECUTED")
            assert_that(negative_output).described_as(
                "unsatisfied condition does not expose the configured property value"
            ).does_not_contain("FLOW_PROPERTY=FLOW_ENABLED_VALUE")
        finally:
            node.tools[Rm].remove_directory(str(work_dir))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: Filtering changes configured tokens\n"
            "in copied text without consuming tokens that have no associated\n"
            "filter.\n"
            "\n"
            "Corpus obligation: pkg:ant/copy-resources/filtered-text\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_copy_resources_filtered_text(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/copy-resources/filtered-text."""
        log.info("Verifying obligation pkg:ant/copy-resources/filtered-text")
        root = node.get_pure_path("/tmp/lisa-ant-copy-filtered-text")
        build = root / "build.xml"
        configured_source = root / "configured.txt"
        unconfigured_source = root / "unconfigured.txt"
        output = root / "out"
        configured_copy = output / "configured.txt"
        unconfigured_copy = output / "unconfigured.txt"
        node.tools[Rm].remove_directory(str(root))
        try:
            node.tools[Mkdir].create_directory(str(root))
            node.tools[Mkdir].create_directory(str(output))
            node.tools[Tee].write_to_file("configured=@configured@", configured_source)
            node.tools[Tee].write_to_file(
                "unconfigured=@unconfigured@", unconfigured_source
            )
            build_text = (
                '<project name="filter-copy" default="filtered">'
                '<target name="filtered">'
                '<copy file="configured.txt" tofile="out/configured.txt" '
                'filtering="true">'
                "<filterset>"
                '<filter token="configured" value="expanded-value"/>'
                "</filterset>"
                "</copy>"
                "</target>"
                '<target name="unconfigured">'
                '<copy file="unconfigured.txt" '
                'tofile="out/unconfigured.txt" filtering="true">'
                "<filterset>"
                '<filter token="configured" value="expanded-value"/>'
                "</filterset>"
                "</copy>"
                "</target>"
                "</project>"
            )
            node.tools[Tee].write_to_file(build_text, build)
            filtered_result = node.execute("ant -f build.xml filtered", cwd=root)
            assert_that(filtered_result.exit_code).described_as(
                "copying text with a configured filter succeeds"
            ).is_equal_to(0)
            filtered_text = node.tools[Cat].read(str(configured_copy))
            assert_that(filtered_text.strip()).described_as(
                "the configured token is expanded in the copied text"
            ).is_equal_to("configured=expanded-value")
            unconfigured_result = node.execute(
                "ant -f build.xml unconfigured", cwd=root
            )
            assert_that(unconfigured_result.exit_code).described_as(
                "copying text with no matching filter succeeds"
            ).is_equal_to(0)
            unconfigured_text = node.tools[Cat].read(str(unconfigured_copy))
            assert_that(unconfigured_text.strip()).described_as(
                "a token without an associated filter remains unchanged"
            ).is_equal_to("unconfigured=@unconfigured@")
        finally:
            node.tools[Rm].remove_directory(str(root))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: A requested target can rely on\n"
            "prerequisite targets without duplicating work along shared\n"
            "dependency chains.\n"
            "\n"
            "Corpus obligation: pkg:ant/dependency-order\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_dependency_order(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/dependency-order."""
        log.info("Verifying obligation pkg:ant/dependency-order")
        work_dir = node.get_pure_path(f"/tmp/lisa-{node.name}-ant-dependency-order")
        build_file = work_dir / "build.xml"
        with_dependencies = (
            '<project name="dependency-order" default="requested">\n'
            '  <target name="shared">\n'
            '    <echo message="SHARED_MARK"/>\n'
            "  </target>\n"
            '  <target name="left" depends="shared">\n'
            '    <echo message="LEFT_MARK"/>\n'
            "  </target>\n"
            '  <target name="right" depends="shared">\n'
            '    <echo message="RIGHT_MARK"/>\n'
            "  </target>\n"
            '  <target name="requested" depends="left,right">\n'
            '    <echo message="REQUEST_MARK"/>\n'
            "  </target>\n"
            "</project>"
        )
        without_dependency = (
            '<project name="dependency-order" default="requested">\n'
            '  <target name="shared">\n'
            '    <echo message="SHARED_MARK"/>\n'
            "  </target>\n"
            '  <target name="left" depends="shared">\n'
            '    <echo message="LEFT_MARK"/>\n'
            "  </target>\n"
            '  <target name="right" depends="shared">\n'
            '    <echo message="RIGHT_MARK"/>\n'
            "  </target>\n"
            '  <target name="requested" depends="left">\n'
            '    <echo message="REQUEST_MARK"/>\n'
            "  </target>\n"
            "</project>"
        )
        node.tools[Mkdir].create_directory(str(work_dir))
        try:
            node.tools[Tee].write_to_file(
                with_dependencies, build_file, append=False, sudo=False
            )
            with_result = node.execute(
                "ant -f build.xml requested",
                cwd=work_dir,
            )
            with_output = f"{with_result.stdout}\n{with_result.stderr}"
            with_markers = [
                "SHARED_MARK",
                "LEFT_MARK",
                "RIGHT_MARK",
                "REQUEST_MARK",
            ]
            with_counts = [with_output.count(marker) for marker in with_markers]
            with_positions = [with_output.find(marker) for marker in with_markers]
            assert_that(with_counts).described_as(
                "dependency chain runs each target once"
            ).is_equal_to([1, 1, 1, 1])
            assert_that(with_positions).described_as(
                "prerequisites precede the requested target in dependency order"
            ).is_equal_to(sorted(with_positions))

            node.tools[Tee].write_to_file(
                without_dependency, build_file, append=False, sudo=False
            )
            without_result = node.execute(
                "ant -f build.xml requested",
                cwd=work_dir,
            )
            without_output = f"{without_result.stdout}\n{without_result.stderr}"
            remaining_markers = [
                "SHARED_MARK",
                "LEFT_MARK",
                "REQUEST_MARK",
            ]
            remaining_counts = [
                without_output.count(marker) for marker in remaining_markers
            ]
            remaining_positions = [
                without_output.find(marker) for marker in remaining_markers
            ]
            assert_that(remaining_counts).described_as(
                "remaining dependency chain runs each target once"
            ).is_equal_to([1, 1, 1])
            assert_that(remaining_positions).described_as(
                "remaining prerequisite precedes the requested target"
            ).is_equal_to(sorted(remaining_positions))
            assert_that(without_output.count("RIGHT_MARK")).described_as(
                "removed prerequisite does not run without its declaration"
            ).is_equal_to(0)
        finally:
            node.tools[Rm].remove_directory(str(work_dir))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: Directory preparation creates\n"
            "missing parent directories and tolerates an already prepared\n"
            "destination.\n"
            "\n"
            "Corpus obligation: pkg:ant/directory-preparation\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_directory_preparation(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/directory-preparation."""
        log.info("Verifying obligation pkg:ant/directory-preparation")
        work = node.get_pure_path("/tmp/lisa-ant-directory-preparation")
        build_file = work / "build.xml"
        tree = work / "ant-tree"
        parent = tree / "ant-parent"
        destination = parent / "ant-destination"
        marker = destination / "preserved-marker.txt"
        build_text = (
            '<project name="directory-preparation" default="prepare">\n'
            '  <target name="other">\n'
            '    <echo message="unused"/>\n'
            "  </target>\n"
            '  <target name="prepare">\n'
            '    <mkdir dir="ant-tree/ant-parent/ant-destination"/>\n'
            "  </target>\n"
            "</project>\n"
        )
        rm = node.tools[Rm]
        mkdir = node.tools[Mkdir]
        tee = node.tools[Tee]
        finder = node.tools[Find]
        cat = node.tools[Cat]
        rm.remove_directory(str(work))
        try:
            mkdir.create_directory(str(work))
            tee.write_to_file(build_text, build_file)
            initial_dirs = finder.find_files(
                work,
                name_pattern=["ant-tree", "ant-parent", "ant-destination"],
                file_type="d",
                force_run=True,
            )
            assert_that(initial_dirs).described_as(
                "the requested directory tree starts entirely missing"
            ).is_empty()

            first = node.execute("ant -f build.xml prepare", cwd=work)
            assert_that(first.exit_code).described_as(
                "the first Ant run succeeds while preparing the missing tree"
            ).is_equal_to(0)
            created_dirs = finder.find_files(
                work,
                name_pattern=["ant-tree", "ant-parent", "ant-destination"],
                file_type="d",
                force_run=True,
            )
            assert_that(created_dirs).described_as(
                "the first Ant run creates the destination and every missing parent"
            ).contains(str(tree), str(parent), str(destination))

            tee.write_to_file("preserved-marker", marker)
            second = node.execute("ant -f build.xml prepare", cwd=work)
            assert_that(second.exit_code).described_as(
                "the second Ant run tolerates the already prepared destination"
            ).is_equal_to(0)
            remaining_dirs = finder.find_files(
                work,
                name_pattern=["ant-tree", "ant-parent", "ant-destination"],
                file_type="d",
                force_run=True,
            )
            assert_that(remaining_dirs).described_as(
                "the second Ant run leaves the existing directory tree in place"
            ).contains(str(tree), str(parent), str(destination))
            marker_content = cat.read(str(marker), force_run=True)
            assert_that(marker_content).described_as(
                "the second Ant run does not recreate the prepared destination"
            ).contains("preserved-marker")
        finally:
            rm.remove_directory(str(work))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: A build can turn the presence or\n"
            "absence of a required property into an explicit diagnostic\n"
            "failure.\n"
            "\n"
            "Corpus obligation: pkg:ant/failure-handling/deliberate-diagnostic\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_failure_handling_deliberate_diagnostic(
        self, node: Node, log: Logger
    ) -> None:
        """Verify obligation pkg:ant/failure-handling/deliberate-diagnostic."""
        log.info("Verifying obligation pkg:ant/failure-handling/deliberate-diagnostic")
        work_dir = node.get_pure_path(f"/tmp/lisa-ant-deliberate-diagnostic-{id(node)}")
        build_file = work_dir / "build.xml"
        build_xml = (
            '<project name="deliberate-diagnostic" default="conditional">\n'
            '  <target name="always-fails">\n'
            '    <fail message="UNCONDITIONAL_FAILURE"/>\n'
            "  </target>\n"
            '  <target name="independent">\n'
            '    <echo message="INDEPENDENT_TARGET"/>\n'
            "  </target>\n"
            '  <target name="conditional">\n'
            '    <fail if="required.property" '
            'message="REQUIRED_PROPERTY_DIAGNOSTIC" status="23"/>\n'
            '    <echo message="CONDITION_BYPASSED"/>\n'
            "  </target>\n"
            "</project>"
        )
        node.tools[Mkdir].create_directory(str(work_dir))
        node.tools[Tee].write_to_file(build_xml, build_file)
        try:
            failed = node.execute(
                "ant -Drequired.property=true",
                cwd=work_dir,
            )
            failure_text = failed.stdout + failed.stderr
            assert_that(failed.exit_code).described_as(
                "satisfied condition exits with the selected failure status"
            ).is_equal_to(23)
            assert_that(failure_text).described_as(
                "satisfied condition reports the configured diagnostic"
            ).contains("REQUIRED_PROPERTY_DIAGNOSTIC")
            assert_that(failure_text).described_as(
                "satisfied condition halts before the following task"
            ).does_not_contain("CONDITION_BYPASSED")

            clear = node.execute("ant", cwd=work_dir)
            clear_text = clear.stdout + clear.stderr
            assert_that(clear.exit_code).described_as(
                "unsatisfied condition allows the build to succeed"
            ).is_equal_to(0)
            assert_that(clear_text).described_as(
                "unsatisfied condition does not emit the failure diagnostic"
            ).does_not_contain("REQUIRED_PROPERTY_DIAGNOSTIC")
            assert_that(clear_text).described_as(
                "unsatisfied condition allows the following task to run"
            ).contains("CONDITION_BYPASSED")
        finally:
            node.tools[Rm].remove_directory(str(work_dir))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: Keep-going behavior distinguishes\n"
            "independent work from targets blocked by a failed dependency.\n"
            "\n"
            "Corpus obligation: pkg:ant/failure-handling/keep-going\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_failure_handling_keep_going(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/failure-handling/keep-going."""
        log.info("Verifying obligation pkg:ant/failure-handling/keep-going")
        work_dir = node.get_pure_path("/tmp/lisa-ant-keep-going")
        build_file = work_dir / "build.xml"
        node.tools[Rm].remove_directory(str(work_dir))
        node.tools[Mkdir].create_directory(str(work_dir))
        build_xml = (
            '<project name="keep-going-test" default="requested">\n'
            '  <condition property="must.fail">\n'
            '    <equals arg1="${trigger.failure}" arg2="yes"/>\n'
            "  </condition>\n"
            '  <target name="fail">\n'
            '    <fail if="must.fail" message="FAILURE_DIAGNOSTIC"/>\n'
            "  </target>\n"
            '  <target name="independent">\n'
            '    <echo message="INDEPENDENT_EXECUTED"/>\n'
            "  </target>\n"
            '  <target name="blocked" depends="fail">\n'
            '    <echo message="BLOCKED_EXECUTED"/>\n'
            "  </target>\n"
            '  <target name="requested" '
            'depends="fail,independent,blocked"/>\n'
            "</project>"
        )
        node.tools[Tee].write_to_file(build_xml, build_file)
        try:
            normal = node.execute(
                "ant -Dtrigger.failure=yes",
                cwd=work_dir,
                expected_exit_code=None,
            )
            keep_going = node.execute(
                "ant -k -Dtrigger.failure=yes",
                cwd=work_dir,
                expected_exit_code=None,
            )
            normal_output = normal.stdout + normal.stderr
            keep_output = keep_going.stdout + keep_going.stderr
            assert_that(normal.exit_code).described_as(
                "the deliberate failure makes the normal build fail"
            ).is_not_equal_to(0)
            assert_that(normal_output).described_as(
                "the normal build reports the deliberate failure diagnostic"
            ).contains("FAILURE_DIAGNOSTIC")
            assert_that(normal_output).described_as(
                "normal mode stops before the independent target executes"
            ).does_not_contain("INDEPENDENT_EXECUTED")
            assert_that(normal_output).described_as(
                "normal mode does not execute the target blocked by failure"
            ).does_not_contain("BLOCKED_EXECUTED")
            assert_that(keep_going.exit_code).described_as(
                "keep-going mode still reports the build failure"
            ).is_not_equal_to(0)
            assert_that(keep_output).described_as(
                "keep-going mode reports the deliberate failure diagnostic"
            ).contains("FAILURE_DIAGNOSTIC")
            assert_that(keep_output).described_as(
                "keep-going mode executes work independent of the failure"
            ).contains("INDEPENDENT_EXECUTED")
            assert_that(keep_output).described_as(
                "keep-going mode skips the target blocked by the failed dependency"
            ).does_not_contain("BLOCKED_EXECUTED")
            unblocked = node.execute(
                "ant -Dtrigger.failure=no blocked",
                cwd=work_dir,
                expected_exit_code=None,
            )
            unblocked_output = unblocked.stdout + unblocked.stderr
            assert_that(unblocked.exit_code).described_as(
                "the dependent target succeeds when its dependency does not fail"
            ).is_equal_to(0)
            assert_that(unblocked_output).described_as(
                "the blocked target marker is observable when the dependency succeeds"
            ).contains("BLOCKED_EXECUTED")
            assert_that(unblocked_output).described_as(
                "the failure diagnostic is absent when its condition is false"
            ).does_not_contain("FAILURE_DIAGNOSTIC")
        finally:
            node.tools[Rm].remove_directory(str(work_dir))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: Java compilation selects source\n"
            "files according to corresponding class-file presence and\n"
            "timestamps.\n"
            "\n"
            "Corpus obligation: pkg:ant/incremental-compilation\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_incremental_compilation(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/incremental-compilation."""
        log.info("Verifying obligation pkg:ant/incremental-compilation")
        root = node.get_pure_path("/tmp/lisa-ant-incremental-compilation")
        node.tools[Rm].remove_directory(str(root))
        try:
            src_dir = root / "src" / "included"
            other_dir = root / "src" / "other"
            class_dir = root / "dest" / "included"
            other_class_dir = root / "dest" / "other"
            node.tools[Mkdir].create_directory(str(src_dir))
            node.tools[Mkdir].create_directory(str(other_dir))
            node.tools[Mkdir].create_directory(str(class_dir))
            node.tools[Mkdir].create_directory(str(other_class_dir))

            build_file = root / "build.xml"
            build_xml = (
                '<project name="incremental" default="compile">\n'
                '  <target name="arrange">\n'
                '    <touch file="src/included/Missing.java" '
                'millis="1640995200000"/>\n'
                '    <touch file="src/included/Newer.java" '
                'millis="1640995200000"/>\n'
                '    <touch file="src/included/Current.java" '
                'millis="1577836800000"/>\n'
                '    <touch file="src/included/Excluded.java" '
                'millis="1640995200000"/>\n'
                '    <touch file="src/other/Outside.java" '
                'millis="1640995200000"/>\n'
                '    <touch file="dest/included/Newer.class" '
                'millis="1609459200000"/>\n'
                '    <touch file="dest/included/Current.class" '
                'millis="1609459200000"/>\n'
                '    <touch file="dest/included/Excluded.class" '
                'millis="1609459200000"/>\n'
                '    <touch file="dest/other/Outside.class" '
                'millis="1609459200000"/>\n'
                "  </target>\n"
                '  <target name="compile">\n'
                '    <mkdir dir="dest"/>\n'
                '    <javac srcdir="src" destdir="dest" '
                'includeantruntime="false" '
                'includes="included/*.java" '
                'excludes="included/Excluded.java"/>\n'
                "  </target>\n"
                '  <target name="other-target"/>\n'
                "</project>"
            )
            node.tools[Tee].write_to_file(build_xml, build_file)

            missing_source = (
                "package included;\n"
                "public class Missing {\n"
                "  public static void main(String[] args) {\n"
                '    System.out.println("MISSING_RUN");\n'
                "  }\n"
                "}"
            )
            newer_source = (
                "package included;\n"
                "public class Newer {\n"
                "  public static void main(String[] args) {\n"
                '    System.out.println("NEWER_RUN");\n'
                "  }\n"
                "}"
            )
            current_source = (
                "package included;\n"
                "public class Current {\n"
                "  public static void main(String[] args) {\n"
                '    System.out.println("CURRENT_RUN");\n'
                "  }\n"
                "}"
            )
            excluded_source = (
                "package included;\n"
                "public class Excluded {\n"
                "  public static void main(String[] args) {\n"
                '    System.out.println("EXCLUDED_RUN");\n'
                "  }\n"
                "}"
            )
            outside_source = (
                "package other;\n"
                "public class Outside {\n"
                "  public static void main(String[] args) {\n"
                '    System.out.println("OUTSIDE_RUN");\n'
                "  }\n"
                "}"
            )
            node.tools[Tee].write_to_file(missing_source, src_dir / "Missing.java")
            node.tools[Tee].write_to_file(newer_source, src_dir / "Newer.java")
            node.tools[Tee].write_to_file(current_source, src_dir / "Current.java")
            node.tools[Tee].write_to_file(excluded_source, src_dir / "Excluded.java")
            node.tools[Tee].write_to_file(outside_source, other_dir / "Outside.java")
            node.tools[Tee].write_to_file("NEWER_OLD_CLASS", class_dir / "Newer.class")
            node.tools[Tee].write_to_file("CURRENT_GUARD", class_dir / "Current.class")
            node.tools[Tee].write_to_file("EXCLUDE_GUARD", class_dir / "Excluded.class")
            node.tools[Tee].write_to_file(
                "OUTSIDE_GUARD", other_class_dir / "Outside.class"
            )
            node.execute("ant arrange", cwd=root, expected_exit_code=0)

            node.execute("ant compile", cwd=root, expected_exit_code=0)
            missing_run = node.execute(
                "java -cp dest included.Missing",
                cwd=root,
                expected_exit_code=0,
            )
            newer_run = node.execute(
                "java -cp dest included.Newer",
                cwd=root,
                expected_exit_code=0,
            )
            missing_output = missing_run.stdout + missing_run.stderr
            newer_output = newer_run.stdout + newer_run.stderr
            assert_that(missing_output).described_as(
                "a source without a class file is compiled"
            ).contains("MISSING_RUN")
            assert_that(newer_output).described_as(
                "a source newer than its class file is compiled"
            ).contains("NEWER_RUN")

            node.tools[Tee].write_to_file(
                "MISSING_CURRENT_GUARD", class_dir / "Missing.class"
            )
            node.tools[Tee].write_to_file(
                "NEWER_CURRENT_GUARD", class_dir / "Newer.class"
            )
            node.execute("ant compile", cwd=root, expected_exit_code=0)

            missing_class = node.tools[Cat].read(
                str(class_dir / "Missing.class"), force_run=True
            )
            newer_class = node.tools[Cat].read(
                str(class_dir / "Newer.class"), force_run=True
            )
            current_class = node.tools[Cat].read(
                str(class_dir / "Current.class"), force_run=True
            )
            excluded_class = node.tools[Cat].read(
                str(class_dir / "Excluded.class"), force_run=True
            )
            outside_class = node.tools[Cat].read(
                str(other_class_dir / "Outside.class"), force_run=True
            )
            assert_that(missing_class).described_as(
                "a now-current class file is not recompiled"
            ).contains("MISSING_CURRENT_GUARD")
            assert_that(newer_class).described_as(
                "a refreshed current class file is not recompiled"
            ).contains("NEWER_CURRENT_GUARD")
            assert_that(current_class).described_as(
                "an initially current class file is not recompiled"
            ).contains("CURRENT_GUARD")
            assert_that(excluded_class).described_as(
                "the exclude pattern prevents compilation of a newer source"
            ).contains("EXCLUDE_GUARD")
            assert_that(outside_class).described_as(
                "the include pattern bounds compilation to the selected sources"
            ).contains("OUTSIDE_GUARD")
        finally:
            node.tools[Rm].remove_directory(str(root))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: A build can run a required system\n"
            "command only on an allowed operating system and provide\n"
            "noninteractive input explicitly.\n"
            "\n"
            "Corpus obligation: pkg:ant/platform-command\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_platform_command(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/platform-command."""
        log.info("Verifying obligation pkg:ant/platform-command")
        case_dir = node.get_pure_path("/tmp/lisa-ant-platform-command")
        build_path = case_dir / "build.xml"
        probe_path = case_dir / "InputProbe.java"
        node.tools[Mkdir].create_directory(str(case_dir))
        try:
            build_xml = (
                '<project name="platform-command" default="run">\n'
                '  <target name="run">\n'
                '    <exec executable="java" os="${allowed.os}" '
                'inputstring="TASK_INPUT_MARKER" failonerror="true">\n'
                '      <arg value="InputProbe.java"/>\n'
                '      <arg value="explicit"/>\n'
                "    </exec>\n"
                '    <exec executable="java" os="${allowed.os}" '
                'failonerror="true">\n'
                '      <arg value="InputProbe.java"/>\n'
                '      <arg value="eof"/>\n'
                "    </exec>\n"
                "  </target>\n"
                '  <target name="other"/>\n'
                "</project>"
            )
            probe_source = (
                "import java.nio.charset.StandardCharsets;\n"
                "public class InputProbe {\n"
                "  public static void main(String[] args) throws Exception {\n"
                '    if ("explicit".equals(args[0])) {\n'
                "      String value = new String(System.in.readAllBytes(), "
                "StandardCharsets.UTF_8);\n"
                '      if ("TASK_INPUT_MARKER".equals(value)) {\n'
                '        System.out.println("EXPLICIT_INPUT_AVAILABLE");\n'
                "      } else {\n"
                '        System.out.println("EXPLICIT_INPUT_WRONG");\n'
                "        System.exit(2);\n"
                "      }\n"
                "    } else {\n"
                "      int value = System.in.read();\n"
                "      if (value == -1) {\n"
                '        System.out.println("EOF_FROM_ANT");\n'
                "      } else {\n"
                '        System.out.println("INTERACTIVE_DATA_RECEIVED");\n'
                "        System.exit(3);\n"
                "      }\n"
                "    }\n"
                "  }\n"
                "}"
            )
            node.tools[Tee].write_to_file(build_xml, build_path)
            node.tools[Tee].write_to_file(probe_source, probe_path)

            matching_result = node.execute(
                "ant -f build.xml -Dallowed.os=Linux run",
                cwd=case_dir,
            )
            matching_output = f"{matching_result.stdout}\n{matching_result.stderr}"
            assert_that(matching_result.exit_code).described_as(
                "the allowed target completes after both system commands run"
            ).is_equal_to(0)
            assert_that(matching_output).described_as(
                "the allowed command receives the task supplied input"
            ).contains("EXPLICIT_INPUT_AVAILABLE")
            assert_that(matching_output).described_as(
                "the command without explicit input receives end of file"
            ).contains("EOF_FROM_ANT")
            assert_that(matching_output).described_as(
                "the command does not consume interactive Ant input"
            ).does_not_contain("INTERACTIVE_DATA_RECEIVED")

            outside_result = node.execute(
                "ant -f build.xml -Dallowed.os=OutsideRestriction run",
                cwd=case_dir,
            )
            outside_output = f"{outside_result.stdout}\n{outside_result.stderr}"
            assert_that(outside_result.exit_code).described_as(
                "the target remains valid when restricted commands are skipped"
            ).is_equal_to(0)
            assert_that(outside_output).described_as(
                "the explicitly fed command does not run outside its OS restriction"
            ).does_not_contain("EXPLICIT_INPUT_AVAILABLE")
            assert_that(outside_output).described_as(
                "the EOF-reading command does not run outside its OS restriction"
            ).does_not_contain("EOF_FROM_ANT")
        finally:
            node.tools[Rm].remove_directory(str(case_dir))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: Path-like build values remain usable\n"
            "across operating systems when written with either documented\n"
            "separator.\n"
            "\n"
            "Corpus obligation: pkg:ant/portable-paths\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_portable_paths(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/portable-paths."""
        log.info("Verifying obligation pkg:ant/portable-paths")
        root = node.get_pure_path(f"/tmp/lisa-ant-portable-paths-{node.name}")
        build_file = root / "build.xml"
        colon_build = (
            '<project name="portable-paths" default="show" basedir=".">\n'
            '  <target name="show">\n'
            '    <path id="portable.ref" path="alpha:beta"/>\n'
            '    <echo message="PORTABLE=${toString:portable.ref}"/>\n'
            "  </target>\n"
            "</project>\n"
        )
        semicolon_build = (
            '<project name="portable-paths" default="show" basedir=".">\n'
            '  <target name="show">\n'
            '    <path id="portable.ref" path="alpha;beta"/>\n'
            '    <echo message="PORTABLE=${toString:portable.ref}"/>\n'
            "  </target>\n"
            "</project>\n"
        )
        node.tools[Rm].remove_directory(str(root))
        node.tools[Mkdir].create_directory(str(root))
        node.tools[Mkdir].create_directory(str(root / "alpha"))
        node.tools[Mkdir].create_directory(str(root / "beta"))
        node.tools[Tee].write_to_file(colon_build, build_file)
        try:
            colon_result = node.execute("ant -f build.xml", cwd=root)
            node.tools[Tee].write_to_file(semicolon_build, build_file)
            semicolon_result = node.execute("ant -f build.xml", cwd=root)
            colon_output = colon_result.stdout + colon_result.stderr
            semicolon_output = semicolon_result.stdout + semicolon_result.stderr
            expected = f"PORTABLE={root}/alpha:{root}/beta"
            unconverted = f"PORTABLE={root}/alpha;{root}/beta"
            assert_that(colon_result.exit_code).described_as(
                "colon-separated path build completes"
            ).is_equal_to(0)
            assert_that(semicolon_result.exit_code).described_as(
                "semicolon-separated path build completes"
            ).is_equal_to(0)
            assert_that(colon_output).described_as(
                "colon-separated path resolves with the operating-system separator"
            ).contains(expected)
            assert_that(semicolon_output).described_as(
                "semicolon-separated path resolves with the operating-system separator"
            ).contains(expected)
            assert_that(colon_output).described_as(
                "colon-separated path does not retain a semicolon separator"
            ).does_not_contain(unconverted)
            assert_that(semicolon_output).described_as(
                "semicolon-separated path is converted from the build separator"
            ).does_not_contain(unconverted)
        finally:
            node.tools[Rm].remove_directory(str(root))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: Named properties provide case-\n"
            "sensitive substitutions across subsequent tasks and targets,\n"
            "while command-line values take precedence over values in the\n"
            "buildfile.\n"
            "\n"
            "Corpus obligation: pkg:ant/property-customization\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_property_customization(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/property-customization."""
        log.info("Verifying obligation pkg:ant/property-customization")
        workdir = node.get_pure_path(
            f"/tmp/lisa-ant-property-customization-{node.name}"
        )
        buildfile = workdir / "build.xml"
        buildfile_text = (
            '<project name="property-customization" default="all">\n'
            '  <property name="Greeting" value="BUILDVAL"/>\n'
            '  <property name="greeting" value="LOWVAL"/>\n'
            '  <target name="first">\n'
            "    <echo>SELECTED=${Greeting}</echo>\n"
            "    <echo>LOWER=${greeting}</echo>\n"
            "    <echo>ATTEMPT=LATEVAL</echo>\n"
            '    <property name="Greeting" value="LATEVAL"/>\n'
            "    <echo>AFTER=${Greeting}</echo>\n"
            "  </target>\n"
            '  <target name="later" depends="first">\n'
            "    <echo>TARGET=${Greeting}</echo>\n"
            "    <echo>TARGETLOW=${greeting}</echo>\n"
            "  </target>\n"
            '  <target name="all" depends="later"/>\n'
            "</project>"
        )
        node.tools[Mkdir].create_directory(str(workdir))
        try:
            node.tools[Tee].write_to_file(buildfile_text, buildfile)

            default_result = node.execute("ant -f build.xml", cwd=workdir)
            default_output = f"{default_result.stdout}\n{default_result.stderr}"
            assert_that(default_result.exit_code).described_as(
                "build using the buildfile property completes"
            ).is_equal_to(0)
            assert_that(default_output).described_as(
                "buildfile value expands across tasks and targets"
            ).contains(
                "SELECTED=BUILDVAL",
                "AFTER=BUILDVAL",
                "TARGET=BUILDVAL",
            )
            assert_that(default_output).described_as(
                "property names remain case-sensitive across targets"
            ).contains("LOWER=LOWVAL", "TARGETLOW=LOWVAL")
            assert_that(default_output).described_as(
                "the attempted replacement value is observable"
            ).contains("ATTEMPT=LATEVAL")
            assert_that(default_output).described_as(
                "a selected buildfile property cannot be replaced later"
            ).does_not_contain("AFTER=LATEVAL", "TARGET=LATEVAL")

            override_result = node.execute(
                "ant -f build.xml -DGreeting=CMDVAL",
                cwd=workdir,
            )
            override_output = f"{override_result.stdout}\n{override_result.stderr}"
            assert_that(override_result.exit_code).described_as(
                "build using the command-line property completes"
            ).is_equal_to(0)
            assert_that(override_output).described_as(
                "command-line value expands across tasks and targets"
            ).contains(
                "SELECTED=CMDVAL",
                "AFTER=CMDVAL",
                "TARGET=CMDVAL",
            )
            assert_that(override_output).described_as(
                "command-line capitalization leaves the lowercase property distinct"
            ).contains("LOWER=LOWVAL", "TARGETLOW=LOWVAL")
            assert_that(override_output).described_as(
                "command-line value takes precedence over the buildfile value"
            ).does_not_contain(
                "SELECTED=BUILDVAL",
                "AFTER=BUILDVAL",
                "TARGET=BUILDVAL",
            )
            assert_that(override_output).described_as(
                "the command-line property cannot be replaced by a later task"
            ).does_not_contain("AFTER=LATEVAL", "TARGET=LATEVAL")
        finally:
            node.tools[Rm].remove_directory(str(workdir))

    @TestCaseMetadata(
        description=(
            "Verifies the ant behaviour: Cleanup removes the selected file,\n"
            "link, directory tree, or resources while preserving material\n"
            "outside the selection.\n"
            "\n"
            "Corpus obligation: pkg:ant/selected-removal\n"
            "This test was generated automatically from a behavior corpus."
        ),
        priority=3,
        # Bounds a hang only: measured cases finish in under 20 seconds.
        timeout=1800,
        tags=["ai-generated"],
    )
    def verify_selected_removal(self, node: Node, log: Logger) -> None:
        """Verify obligation pkg:ant/selected-removal."""
        log.info("Verifying obligation pkg:ant/selected-removal")
        base = node.get_pure_path("/tmp/lisa-ant-selected-removal")
        initial_entries = node.tools[Find].find_files(
            base,
            ignore_not_exist=True,
            force_run=True,
        )
        assert_that(initial_entries).described_as(
            "fixture directory starts absent"
        ).is_empty()
        node.tools[Mkdir].create_directory(str(base))
        try:
            default_dir = base / "default-tree" / "chosen"
            requested_dir = base / "requested-tree" / "chosen"
            outside_dir = base / "outside"
            node.tools[Mkdir].create_directory(str(default_dir))
            node.tools[Mkdir].create_directory(str(requested_dir))
            node.tools[Mkdir].create_directory(str(outside_dir))

            build_file = base / "build.xml"
            build_xml = (
                '<project name="selected-removal" default="cleanup">\n'
                '  <target name="cleanup">\n'
                '    <delete includeEmptyDirs="false">\n'
                '      <fileset dir="default-tree" includes="chosen/**"/>\n'
                "    </delete>\n"
                '    <delete includeEmptyDirs="true">\n'
                '      <fileset dir="requested-tree" '
                'includes="chosen/**"/>\n'
                "    </delete>\n"
                "  </target>\n"
                '  <target name="other"/>\n'
                "</project>"
            )
            node.tools[Tee].write_to_file(build_xml, build_file)
            node.tools[Tee].write_to_file(
                "selected-resource",
                default_dir / "default-item.tmp",
            )
            node.tools[Tee].write_to_file(
                "requested-resource",
                requested_dir / "requested-item.tmp",
            )
            node.tools[Tee].write_to_file(
                "preserved-resource",
                outside_dir / "preserved.keep",
            )

            first = node.execute("ant", cwd=base)
            assert_that(first.exit_code).described_as(
                "cleanup target completes for selected resources"
            ).is_equal_to(0)
            after_first = node.tools[Find].find_files(base, force_run=True)
            assert_that(
                any(path.endswith("/default-item.tmp") for path in after_first)
            ).described_as("cleanup removes the selected default resource").is_false()
            assert_that(
                any(path.endswith("/outside/preserved.keep") for path in after_first)
            ).described_as("cleanup preserves material outside the selection").is_true()
            assert_that(
                any(path.endswith("/default-tree/chosen") for path in after_first)
            ).described_as(
                "fileset keeps an empty directory when removal is not requested"
            ).is_true()
            assert_that(
                any(path.endswith("/requested-tree/chosen") for path in after_first)
            ).described_as(
                "fileset removes an empty directory when removal is requested"
            ).is_false()

            node.tools[Tee].write_to_file(
                "selected-resource",
                outside_dir / "changed.keep",
            )
            second = node.execute("ant", cwd=base)
            assert_that(second.exit_code).described_as(
                "cleanup target completes after the resource leaves the selection"
            ).is_equal_to(0)
            after_second = node.tools[Find].find_files(base, force_run=True)
            assert_that(
                any(path.endswith("/outside/changed.keep") for path in after_second)
            ).described_as(
                "cleanup preserves the changed resource outside the selection"
            ).is_true()
            assert_that(
                any(path.endswith("/outside/preserved.keep") for path in after_second)
            ).described_as(
                "repeated cleanup still preserves other unselected material"
            ).is_true()
        finally:
            node.tools[Rm].remove_directory(str(base))
