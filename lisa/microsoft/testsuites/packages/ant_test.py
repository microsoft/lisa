# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Release-gate tests for ant on Azure Linux.

Each case verifies one reviewed behaviour obligation directly against the node under
test.

Generated from a reviewed behaviour corpus by the Azure Linux release gate. Every
obligation below was first verified on a provisioned Azure Linux 4.0 guest on both
x86_64 and aarch64 before being re-expressed here.

Each case names the corpus obligation it discharges, so a failure upstream can be traced
back to the behaviour that was promised rather than to the test that happened to break.
"""

from __future__ import annotations

import re
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
from lisa.operating_system import CBLMariner, Posix
from lisa.util import SkippedException


def combined_output(result: Any) -> str:
    """Return one command result's streams merged and normalised to LF.

    A case controls the markers it prints but not which stream a tool writes a
    diagnostic to, and LISA runs every command on a pty that rewrites each newline
    as a carriage-return pair. Merging stdout and stderr removes the guess that made
    a case watch the wrong stream, and normalising the carriage returns removes the
    mismatch that made marker parsing silently fail.

    Args:
        result: The value ``node.execute`` returned.

    Returns:
        The command's stdout and stderr joined by a newline, with every CRLF and lone
        carriage return rewritten to a single LF.
    """
    merged = f"{result.stdout}\n{result.stderr}"
    return merged.replace("\r\n", "\n").replace("\r", "\n")


def section(text: str, begin: str, end: str) -> str:
    """Return the text framed by the `begin` and `end` markers.

    The end marker is located wherever it appears, so one printed as the final line --
    whose trailing newline the pty strips -- is still found rather than missed, which
    is the failure that made a hand-rolled ``split`` return the whole output as if it
    were data. An absent marker raises instead of returning everything, so a genuinely
    missing region fails loudly rather than passing. Pass an empty `begin` to take
    everything before `end`.

    Args:
        text: The combined, normalised output, from :func:`combined_output`.
        begin: The marker opening the region, or "" to start at the first character.
        end: The marker closing the region.

    Returns:
        The characters between the markers, without the markers themselves or the
        newlines adjoining them.

    Raises:
        ValueError: If either marker is absent from `text`.
    """
    start = text.find(begin)
    if start < 0:
        raise ValueError(f"begin marker {begin!r} not found in guest output")
    start += len(begin)
    stop = text.find(end, start)
    if stop < 0:
        raise ValueError(f"end marker {end!r} not found in guest output")
    return text[start:stop].strip("\n")


def section_lines(text: str, begin: str, end: str) -> list[str]:
    """Return the lines of the region framed by `begin` and `end`.

    A caller counting them sees exactly what the guest printed between the markers,
    with no spurious trailing empty entry from the newline before the end marker --
    the miscount that made a hand-rolled ``split`` assert the wrong length.

    Args:
        text: The combined, normalised output, from :func:`combined_output`.
        begin: The marker opening the region, or "" to start at the first character.
        end: The marker closing the region.

    Returns:
        The region's lines, empty when the region itself is empty.

    Raises:
        ValueError: If either marker is absent from `text`.
    """
    body = section(text, begin, end)
    return body.split("\n") if body else []


@TestSuiteMetadata(
    area="packages",
    category="functional",
    description="""
        Release-gate tests for ant on Azure Linux.

        Each case verifies one reviewed behaviour obligation directly against the node
        under test.
    """,
    requirement=simple_requirement(supported_os=[CBLMariner]),
    maturity="preview",
    tags=["ai-generated"],
)
class AntSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        assert isinstance(node.os, Posix)
        node.os.install_packages(
            [
                "ant",
                "java-25-openjdk-devel",
                "junit",
                "ant-junit",
            ]
        )

    @TestCaseMetadata(
        description="""
            Verifies that Ant normalizes portable path separators to the host form and
            evaluates composed host conditions. It also proves boolean conditions
            short-circuit and only the Linux-appropriate target performs work.

            Corpus obligation: pkg:ant/adapt-to-host-platform
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_adapt_to_host_platform(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        script = r"""
set -u
tmp=$(mktemp -d /tmp/ant-platform.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cat <<'XML' > "$tmp/build.xml"
<project name="host-platform" default="verify" basedir=".">
    <target name="prepare">
        <property
            name="portable.path"
            value="${basedir}\one.txt;${basedir}/two.txt"
        />
        <pathconvert
            property="host.path"
            pathsep=":"
            dirsep="/"
        >
            <path path="${portable.path}" />
        </pathconvert>
        <condition property="path.ok">
            <equals
                arg1="${host.path}"
                arg2="${basedir}/one.txt:${basedir}/two.txt"
            />
        </condition>
        <condition property="host.ok">
            <and>
                <os family="unix" />
                <os
                    name="${os.name}"
                    arch="${os.arch}"
                    version="${os.version}"
                />
                <equals
                    arg1="${os.name}"
                    arg2="Linux"
                />
            </and>
        </condition>
        <condition property="or.short">
            <or>
                <istrue value="true" />
                <matches string="x" pattern="[" />
            </or>
        </condition>
        <condition property="and.short">
            <and>
                <istrue value="false" />
                <matches string="x" pattern="[" />
            </and>
        </condition>
    </target>
    <target name="linux-work" depends="prepare" if="host.ok">
        <touch file="${basedir}/linux-work-ran" />
        <echo message="PLATFORM_WORK=linux" />
    </target>
    <target name="other-work" depends="prepare" unless="host.ok">
        <touch file="${basedir}/other-work-ran" />
        <echo message="PLATFORM_WORK=other" />
    </target>
    <target name="verify" depends="linux-work,other-work">
        <fail unless="path.ok" message="portable path conversion failed" />
        <fail unless="host.ok" message="host condition did not match" />
        <fail unless="or.short" message="or condition did not pass" />
        <fail if="and.short" message="and condition unexpectedly passed" />
        <echo message="PATH_OK=true" />
        <echo message="HOST_OK=true" />
        <echo message="OR_SHORT=true" />
        <echo message="AND_SHORT=not-set" />
    </target>
</project>
XML
printf 'PACKAGE_BEGIN\n'
rpm -q --qf 'ant %{VERSION}-%{RELEASE}\n' ant
rpm_rc=$?
printf 'RPM_RC=%s\n' "$rpm_rc"
ant -version
version_rc=$?
printf 'VERSION_RC=%s\n' "$version_rc"
printf 'PACKAGE_END\n'
ant -f "$tmp/build.xml" verify > "$tmp/ant.out" 2>&1
ant_rc=$?
printf 'BUILD_BEGIN\n'
cat "$tmp/ant.out"
printf 'BUILD_END\n'
if test -f "$tmp/linux-work-ran"; then right=yes; else right=no; fi
if test -f "$tmp/other-work-ran"; then wrong=yes; else wrong=no; fi
printf 'FACTS_BEGIN\n'
printf 'ANT_RC=%s\n' "$ant_rc"
printf 'LINUX_WORK=%s\n' "$right"
printf 'OTHER_WORK=%s\n' "$wrong"
printf 'FACTS_END\n'
exit 0
"""
        result = node.execute(script, shell=True)
        text = combined_output(result)
        package = section(text, "PACKAGE_BEGIN", "PACKAGE_END")
        build = section(text, "BUILD_BEGIN", "BUILD_END")
        facts = section(text, "FACTS_BEGIN", "FACTS_END")
        assert_that(result.exit_code).described_as(
            f"guest probe must complete; observed output: {text}"
        ).is_equal_to(0)
        assert_that(package).described_as(
            f"Ant RPM must be present; observed package data: {package}"
        ).contains("RPM_RC=0")
        assert_that(package).described_as(
            f"Ant command must run; observed package data: {package}"
        ).contains("VERSION_RC=0")
        assert_that(package).described_as(
            f"RPM identity must name Ant; observed package data: {package}"
        ).matches(r"(?m)^ant .+")
        assert_that(facts).described_as(
            f"Ant build must succeed; observed facts: {facts}"
        ).contains("ANT_RC=0")
        assert_that(build).described_as(
            f"portable path conversion must pass; observed build: {build}"
        ).contains("PATH_OK=true")
        assert_that(build).described_as(
            f"composed host detection must pass; observed build: {build}"
        ).contains("HOST_OK=true")
        assert_that(build).described_as(
            f"or must short-circuit invalid regex; observed build: {build}"
        ).contains("OR_SHORT=true")
        assert_that(build).described_as(
            f"and must short-circuit invalid regex; observed build: {build}"
        ).contains("AND_SHORT=not-set")
        assert_that(facts).described_as(
            f"Linux work must run; observed facts: {facts}"
        ).contains("LINUX_WORK=yes")
        assert_that(facts).described_as(
            f"non-Linux work must not run; observed facts: {facts}"
        ).contains("OTHER_WORK=no")
        assert_that(build).described_as(
            f"platform target must be Linux; observed build: {build}"
        ).contains("PLATFORM_WORK=linux")
        assert_that(build).described_as(
            f"other target must be skipped; observed build: {build}"
        ).does_not_contain("PLATFORM_WORK=other")

    @TestCaseMetadata(
        description="""
            Verifies Ant's Java compilation target creates missing class files,
            recompiles stale sources, and leaves current class files unchanged. It also
            verifies that a Java syntax error fails the build by default and does not
            produce a class file.

            Corpus obligation: pkg:ant/compile-java
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_compile_java(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        target = "compile"
        script = rf"""
tmp=$(mktemp -d /tmp/ant-compile-java.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/src" "$tmp/classes"
cat <<'XML' > "$tmp/build.xml"
<project name="compile-probe" default="{target}" basedir=".">
  <property name="src.dir" location="src"/>
  <property name="build.dir" location="classes"/>
  <target name="{target}">
    <mkdir dir="${{build.dir}}"/>
    <javac srcdir="${{src.dir}}" destdir="${{build.dir}}"
           includeantruntime="false"/>
  </target>
</project>
XML
cat <<'JAVA' > "$tmp/src/Missing.java"
public class Missing {{}}
JAVA
cat <<'JAVA' > "$tmp/src/Stale.java"
public class Stale {{}}
JAVA
cat <<'JAVA' > "$tmp/src/Current.java"
public class Current {{}}
JAVA
ant -f "$tmp/build.xml" {target} > "$tmp/initial.log" 2>&1
initial_rc=$?
[ -s "$tmp/classes/Missing.class" ] && initial_missing=YES || \
    initial_missing=NO
[ -s "$tmp/classes/Stale.class" ] && initial_stale=YES || \
    initial_stale=NO
[ -s "$tmp/classes/Current.class" ] && initial_current=YES || \
    initial_current=NO
prep_rc=0
if [ "$initial_rc" -eq 0 ]; then
    touch -d '@1700000000' "$tmp/src/Stale.java" || prep_rc=1
    touch -d '@1690000000' "$tmp/classes/Stale.class" || prep_rc=1
    touch -d '@1690000000' "$tmp/src/Current.java" || prep_rc=1
    touch -d '@1700000000' "$tmp/classes/Current.class" || prep_rc=1
    rm -f "$tmp/classes/Missing.class" || prep_rc=1
else
    prep_rc=1
fi
[ ! -e "$tmp/classes/Missing.class" ] && missing_before=NO || \
    missing_before=YES
stale_before=$(stat -c %Y "$tmp/classes/Stale.class" 2>/dev/null || \
    echo MISSING)
current_before=$(stat -c %Y "$tmp/classes/Current.class" 2>/dev/null || \
    echo MISSING)
if [ "$prep_rc" -eq 0 ]; then
    ant -f "$tmp/build.xml" {target} > "$tmp/incremental.log" 2>&1
    incremental_rc=$?
else
    incremental_rc=NOT_RUN
fi
[ -s "$tmp/classes/Missing.class" ] && missing_after=YES || \
    missing_after=NO
[ -s "$tmp/classes/Stale.class" ] && stale_after_exists=YES || \
    stale_after_exists=NO
stale_after=$(stat -c %Y "$tmp/classes/Stale.class" 2>/dev/null || \
    echo MISSING)
current_after=$(stat -c %Y "$tmp/classes/Current.class" 2>/dev/null || \
    echo MISSING)
if [ "$incremental_rc" = 0 ]; then
    cat <<'JAVA' > "$tmp/src/Broken.java"
public class Broken {{ this is not Java; }}
JAVA
    ant -f "$tmp/build.xml" {target} > "$tmp/error.log" 2>&1
    broken_rc=$?
else
    broken_rc=NOT_RUN
fi
[ -e "$tmp/classes/Broken.class" ] && broken_class=YES || \
    broken_class=NO
printf '%s\n' FACTS_BEGIN
printf 'INITIAL_RC=%s\n' "$initial_rc"
printf 'INITIAL_MISSING=%s\n' "$initial_missing"
printf 'INITIAL_STALE=%s\n' "$initial_stale"
printf 'INITIAL_CURRENT=%s\n' "$initial_current"
printf 'PREP_RC=%s\n' "$prep_rc"
printf 'MISSING_BEFORE=%s\n' "$missing_before"
printf 'INCREMENTAL_RC=%s\n' "$incremental_rc"
printf 'MISSING_AFTER=%s\n' "$missing_after"
printf 'STALE_AFTER_EXISTS=%s\n' "$stale_after_exists"
printf 'STALE_BEFORE=%s\n' "$stale_before"
printf 'STALE_AFTER=%s\n' "$stale_after"
printf 'CURRENT_BEFORE=%s\n' "$current_before"
printf 'CURRENT_AFTER=%s\n' "$current_after"
printf 'BROKEN_RC=%s\n' "$broken_rc"
printf 'BROKEN_CLASS=%s\n' "$broken_class"
printf '%s\n' FACTS_END
printf '%s\n' ERROR_BEGIN
cat "$tmp/error.log" 2>/dev/null || printf '%s\n' NO_ERROR_LOG
printf '%s\n' ERROR_END
"""
        result = node.execute(script, shell=True)
        text = combined_output(result)
        fact_lines = section_lines(text, "FACTS_BEGIN", "FACTS_END")
        facts = {}
        for line in fact_lines:
            key, value = line.split("=", 1)
            facts[key] = value
        error_text = section(text, "ERROR_BEGIN", "ERROR_END")
        assert_that(result.exit_code).described_as(
            f"guest probe exit code was {result.exit_code}, expected 0"
        ).is_equal_to(0)
        assert_that(facts["INITIAL_RC"]).described_as(
            f"initial Ant compile rc was {facts['INITIAL_RC']}, expected 0"
        ).is_equal_to("0")
        assert_that(facts["INITIAL_MISSING"]).described_as(
            f"initial Missing.class state was {facts['INITIAL_MISSING']}"
        ).is_equal_to("YES")
        assert_that(facts["INITIAL_STALE"]).described_as(
            f"initial Stale.class state was {facts['INITIAL_STALE']}"
        ).is_equal_to("YES")
        assert_that(facts["INITIAL_CURRENT"]).described_as(
            f"initial Current.class state was {facts['INITIAL_CURRENT']}"
        ).is_equal_to("YES")
        assert_that(facts["PREP_RC"]).described_as(
            f"incremental-test preparation rc was {facts['PREP_RC']}"
        ).is_equal_to("0")
        assert_that(facts["MISSING_BEFORE"]).described_as(
            "Missing.class before incremental compile was "
            f"{facts['MISSING_BEFORE']}, expected NO"
        ).is_equal_to("NO")
        assert_that(facts["INCREMENTAL_RC"]).described_as(
            f"incremental Ant compile rc was {facts['INCREMENTAL_RC']}, expected 0"
        ).is_equal_to("0")
        assert_that(facts["MISSING_AFTER"]).described_as(
            "Missing.class after incremental compile was "
            f"{facts['MISSING_AFTER']}, expected YES"
        ).is_equal_to("YES")
        assert_that(facts["STALE_AFTER_EXISTS"]).described_as(
            "Stale.class after incremental compile was "
            f"{facts['STALE_AFTER_EXISTS']}, expected YES"
        ).is_equal_to("YES")
        assert_that(facts["STALE_BEFORE"]).described_as(
            f"stale class timestamp was {facts['STALE_BEFORE']}, expected digits"
        ).matches(r"^\d+$")
        assert_that(facts["STALE_AFTER"]).described_as(
            f"rebuilt class timestamp was {facts['STALE_AFTER']}, expected digits"
        ).matches(r"^\d+$")
        assert_that(int(facts["STALE_AFTER"])).described_as(
            f"stale class timestamps were {facts['STALE_BEFORE']} then "
            f"{facts['STALE_AFTER']}, expected the latter to be newer"
        ).is_greater_than(int(facts["STALE_BEFORE"]))
        assert_that(facts["CURRENT_BEFORE"]).described_as(
            f"current class timestamp was {facts['CURRENT_BEFORE']}, expected digits"
        ).matches(r"^\d+$")
        assert_that(facts["CURRENT_AFTER"]).described_as(
            f"post-build current timestamp was {facts['CURRENT_AFTER']}"
        ).matches(r"^\d+$")
        assert_that(facts["CURRENT_AFTER"]).described_as(
            f"current class timestamps were {facts['CURRENT_BEFORE']} then "
            f"{facts['CURRENT_AFTER']}, expected no rewrite"
        ).is_equal_to(facts["CURRENT_BEFORE"])
        assert_that(facts["BROKEN_RC"]).described_as(
            f"syntax-error build rc was {facts['BROKEN_RC']}, expected numeric"
        ).matches(r"^\d+$")
        assert_that(facts["BROKEN_RC"]).described_as(
            f"syntax-error build rc was {facts['BROKEN_RC']}, expected nonzero"
        ).is_not_equal_to("0")
        assert_that(facts["BROKEN_CLASS"]).described_as(
            f"Broken.class state was {facts['BROKEN_CLASS']}, expected NO"
        ).is_equal_to("NO")
        assert_that(error_text).described_as(
            f"compiler failure output did not identify Broken.java: {error_text}"
        ).contains("Broken.java")

    @TestCaseMetadata(
        description="""
            Verifies Ant discovers the default build file with no build-file argument
            and searches upward when requested. It also verifies an explicit build file
            runs a named target and resolves relative output paths from the build file's
            base directory.

            Corpus obligation: pkg:ant/discover-build
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_discover_build(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        script = r"""
set -eu
tmp=$(mktemp -d /tmp/ant-discover-build.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/noarg" "$tmp/search/deep/child"
mkdir -p "$tmp/explicit" "$tmp/runner"
cat <<'XML' > "$tmp/noarg/build.xml"
<project name="noarg" default="default-target">
    <target name="default-target">
        <mkdir dir="evidence"/>
        <echo file="evidence/noarg.txt">NOARG_DEFAULT</echo>
    </target>
</project>
XML
cat <<'XML' > "$tmp/search/build.xml"
<project name="search" default="found-default">
    <target name="found-default">
        <mkdir dir="relative"/>
        <echo file="relative/find.txt">UPWARD_DEFAULT</echo>
    </target>
</project>
XML
cat <<'XML' > "$tmp/explicit/custom.xml"
<project name="explicit" default="wrong-default">
    <target name="wrong-default">
        <mkdir dir="relative"/>
        <echo file="relative/default.txt">WRONG_DEFAULT</echo>
    </target>
    <target name="chosen">
        <mkdir dir="relative"/>
        <echo file="relative/chosen.txt">EXPLICIT_TARGET</echo>
    </target>
</project>
XML
if (cd "$tmp/noarg" && ant) > "$tmp/noarg.log" 2>&1; then
    noarg_rc=0
else
    noarg_rc=$?
fi
if (cd "$tmp/search/deep/child" && ant -find build.xml) \
    > "$tmp/find.log" 2>&1; then
    find_rc=0
else
    find_rc=$?
fi
if (cd "$tmp/runner" && ant -f ../explicit/custom.xml chosen) \
    > "$tmp/explicit.log" 2>&1; then
    explicit_rc=0
else
    explicit_rc=$?
fi
noarg_value=$(cat "$tmp/noarg/evidence/noarg.txt" 2>/dev/null || \
    printf '%s' MISSING)
find_value=$(cat "$tmp/search/relative/find.txt" 2>/dev/null || \
    printf '%s' MISSING)
explicit_value=$(cat "$tmp/explicit/relative/chosen.txt" 2>/dev/null || \
    printf '%s' MISSING)
if [ -e "$tmp/search/deep/child/relative/find.txt" ]; then
    find_nested=PRESENT
else
    find_nested=ABSENT
fi
if [ -e "$tmp/runner/relative/chosen.txt" ]; then
    explicit_runner=PRESENT
else
    explicit_runner=ABSENT
fi
if [ -e "$tmp/explicit/relative/default.txt" ]; then
    explicit_default=PRESENT
else
    explicit_default=ABSENT
fi
printf '%s\n' ANT_VERSION_BEGIN
ant -version 2>&1 || true
printf '%s\n' ANT_VERSION_END
printf '%s\n' NOARG_LOG_BEGIN
cat "$tmp/noarg.log"
printf '%s\n' NOARG_LOG_END
printf '%s\n' FIND_LOG_BEGIN
cat "$tmp/find.log"
printf '%s\n' FIND_LOG_END
printf '%s\n' EXPLICIT_LOG_BEGIN
cat "$tmp/explicit.log"
printf '%s\n' EXPLICIT_LOG_END
printf '%s\n' RESULT_BEGIN
printf 'NOARG_RC=%s\n' "$noarg_rc"
printf 'NOARG_VALUE=%s\n' "$noarg_value"
printf 'FIND_RC=%s\n' "$find_rc"
printf 'FIND_VALUE=%s\n' "$find_value"
printf 'FIND_NESTED=%s\n' "$find_nested"
printf 'EXPLICIT_RC=%s\n' "$explicit_rc"
printf 'EXPLICIT_VALUE=%s\n' "$explicit_value"
printf 'EXPLICIT_RUNNER=%s\n' "$explicit_runner"
printf 'EXPLICIT_DEFAULT=%s\n' "$explicit_default"
printf '%s\n' RESULT_END
"""
        result = node.execute(script, shell=True)
        assert_that(result.exit_code).described_as(
            "guest evidence script must complete"
        ).is_equal_to(0)
        text = combined_output(result)
        noarg_log = section(text, "NOARG_LOG_BEGIN", "NOARG_LOG_END")
        find_log = section(text, "FIND_LOG_BEGIN", "FIND_LOG_END")
        explicit_log = section(
            text,
            "EXPLICIT_LOG_BEGIN",
            "EXPLICIT_LOG_END",
        )
        summary = section(text, "RESULT_BEGIN", "RESULT_END")
        assert_that(summary).described_as(
            f"no-argument Ant invocation failed; log: {noarg_log}"
        ).contains("NOARG_RC=0")
        assert_that(summary).described_as(
            f"default target evidence was not produced; summary: {summary}"
        ).contains("NOARG_VALUE=NOARG_DEFAULT")
        assert_that(summary).described_as(
            f"upward build search failed; log: {find_log}"
        ).contains("FIND_RC=0")
        assert_that(summary).described_as(
            f"upward search did not run the default target; summary: {summary}"
        ).contains("FIND_VALUE=UPWARD_DEFAULT")
        assert_that(summary).described_as(
            f"searched build used the invocation directory; summary: {summary}"
        ).contains("FIND_NESTED=ABSENT")
        assert_that(summary).described_as(
            f"explicit build invocation failed; log: {explicit_log}"
        ).contains("EXPLICIT_RC=0")
        assert_that(summary).described_as(
            f"named target evidence was not produced; summary: {summary}"
        ).contains("EXPLICIT_VALUE=EXPLICIT_TARGET")
        assert_that(summary).described_as(
            f"explicit build used the invocation directory; summary: {summary}"
        ).contains("EXPLICIT_RUNNER=ABSENT")
        assert_that(summary).described_as(
            f"Ant ran the default instead of the named target; summary: {summary}"
        ).contains("EXPLICIT_DEFAULT=ABSENT")

    @TestCaseMetadata(
        description="""
            Verifies that Ant runs and captures an external command only for an allowed
            operating system. It also checks nonzero exit handling, program startup
            failure, and timeout termination.

            Corpus obligation: pkg:ant/execute-external-command
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_execute_external_command(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        build_xml = r"""
<project name="external-command" default="allowed" basedir=".">
    <target name="allowed">
        <echo message="OS_NAME=${os.name}"/>
        <exec executable="/bin/sh" os="Linux"
              outputproperty="captured.output">
            <arg value="-c"/>
            <arg value="printf ant-external-output"/>
        </exec>
        <echo message="CAPTURED=${captured.output}"/>
    </target>
    <target name="blocked">
        <exec executable="/bin/sh" os="NoMatchOperatingSystem">
            <arg value="-c"/>
            <arg value="printf blocked > '${basedir}/blocked'"/>
        </exec>
    </target>
    <target name="ignored-nonzero">
        <exec executable="/bin/sh" resultproperty="exec.code">
            <arg value="-c"/>
            <arg value="exit 9"/>
        </exec>
        <echo message="IGNORED_RESULT=${exec.code}"/>
    </target>
    <target name="requested-failure">
        <exec executable="/bin/sh" failonerror="true">
            <arg value="-c"/>
            <arg value="exit 9"/>
        </exec>
    </target>
    <target name="missing-program">
        <exec executable="/definitely/not/here"/>
    </target>
    <target name="timeout">
        <exec executable="/bin/sh" timeout="500"
              resultproperty="timer.code">
            <arg value="-c"/>
            <arg value="exec sleep 30"/>
        </exec>
        <echo message="TIMEOUT_RESULT=${timer.code}"/>
    </target>
</project>
"""
        command = rf"""
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat <<'XML' > "$tmp/build.xml"
{build_xml}
XML
if test ! -s "$tmp/build.xml"; then
    echo BUILD_FILE_BEGIN
    echo BUILD_FILE_MISSING
    echo BUILD_FILE_END
    exit 1
fi
run_target() {{
    label=$1
    target=$2
    printf '%s_BEGIN\n' "$label"
    ant -f "$tmp/build.xml" "$target" 2>&1
    rc=$?
    printf 'RC=%s\n' "$rc"
    printf '%s_END\n' "$label"
}}
run_target ALLOWED allowed
run_target BLOCKED blocked
printf 'BLOCKED_STATE_BEGIN\n'
if test -e "$tmp/blocked"; then
    echo BLOCKED_FILE=present
else
    echo BLOCKED_FILE=absent
fi
printf 'BLOCKED_STATE_END\n'
run_target IGNORED ignored-nonzero
run_target REQUESTED requested-failure
run_target MISSING missing-program
run_target TIMEOUT timeout
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        assert_that(result.exit_code).described_as(
            f"guest script must complete; observed output: {text}"
        ).is_equal_to(0)
        allowed_text = section(text, "ALLOWED_BEGIN", "ALLOWED_END")
        assert_that(allowed_text).described_as(
            f"allowed execution must succeed; observed: {allowed_text}"
        ).contains("RC=0")
        assert_that(allowed_text).described_as(
            f"Ant must observe the allowed OS; observed: {allowed_text}"
        ).contains("OS_NAME=Linux")
        assert_that(allowed_text).described_as(
            f"Ant must capture command output; observed: {allowed_text}"
        ).contains("CAPTURED=ant-external-output")
        blocked_text = section(text, "BLOCKED_BEGIN", "BLOCKED_END")
        assert_that(blocked_text).described_as(
            f"OS-suppressed execution must succeed; observed: {blocked_text}"
        ).contains("RC=0")
        blocked_state = section(
            text,
            "BLOCKED_STATE_BEGIN",
            "BLOCKED_STATE_END",
        )
        assert_that(blocked_state).described_as(
            f"disallowed OS command must not run; observed: {blocked_state}"
        ).contains("BLOCKED_FILE=absent")
        ignored_text = section(text, "IGNORED_BEGIN", "IGNORED_END")
        assert_that(ignored_text).described_as(
            f"default nonzero handling must succeed; observed: {ignored_text}"
        ).contains("RC=0")
        assert_that(ignored_text).described_as(
            f"Ant must expose the ignored result; observed: {ignored_text}"
        ).contains("IGNORED_RESULT=9")
        requested_text = section(
            text,
            "REQUESTED_BEGIN",
            "REQUESTED_END",
        )
        requested_codes = re.findall(
            r"^RC=([0-9]+)$",
            requested_text,
            re.MULTILINE,
        )
        assert_that(requested_codes).described_as(
            f"requested-failure status is missing: {requested_text}"
        ).is_length(1)
        requested_code = int(requested_codes[0])
        assert_that(requested_code).described_as(
            f"failonerror must fail the build; observed rc: {requested_code}"
        ).is_not_equal_to(0)
        missing_text = section(text, "MISSING_BEGIN", "MISSING_END")
        missing_codes = re.findall(
            r"^RC=([0-9]+)$",
            missing_text,
            re.MULTILINE,
        )
        assert_that(missing_codes).described_as(
            f"missing-program status is missing; observed: {missing_text}"
        ).is_length(1)
        missing_code = int(missing_codes[0])
        assert_that(missing_code).described_as(
            f"program startup failure must fail Ant; rc: {missing_code}"
        ).is_not_equal_to(0)
        assert_that(missing_text).described_as(
            f"Ant must report its startup failure; observed: {missing_text}"
        ).contains("Cannot run program")
        timeout_text = section(text, "TIMEOUT_BEGIN", "TIMEOUT_END")
        assert_that(timeout_text).described_as(
            f"timeout without failonerror must succeed: {timeout_text}"
        ).contains("RC=0")
        assert_that(timeout_text).described_as(
            f"Ant must report killing the process; observed: {timeout_text}"
        ).contains("Timeout: killed the sub-process")
        timeout_codes = re.findall(
            r"TIMEOUT_RESULT=(-?[0-9]+)",
            timeout_text,
        )
        assert_that(timeout_codes).described_as(
            f"timeout result is missing; observed: {timeout_text}"
        ).is_length(1)
        timeout_code = int(timeout_codes[0])
        assert_that(timeout_code).described_as(
            f"timed-out process must return nonzero; rc: {timeout_code}"
        ).is_not_equal_to(0)

    @TestCaseMetadata(
        description="""
            Verifies that Ant reports its version and runtime diagnostics without
            requiring a project build file. It confirms Apache Ant identification and
            locale information in the diagnostic report.

            Corpus obligation: pkg:ant/inspect-runtime
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_inspect_runtime(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        command = r"""set -u
tmp=$(mktemp -d /tmp/ant-runtime.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
printf '%s\n' BUILD_STATE_BEGIN
if [ -e build.xml ]; then
    printf '%s\n' present
else
    printf '%s\n' absent
fi
printf '%s\n' BUILD_STATE_END
printf '%s\n' VERSION_BEGIN
ant -version 2>&1
version_rc=$?
printf '%s\n' VERSION_END
printf '%s\n' VERSION_RC_BEGIN
printf '%s\n' "$version_rc"
printf '%s\n' VERSION_RC_END
printf '%s\n' DIAGNOSTICS_BEGIN
ant -diagnostics 2>&1
diagnostics_rc=$?
printf '%s\n' DIAGNOSTICS_END
printf '%s\n' DIAGNOSTICS_RC_BEGIN
printf '%s\n' "$diagnostics_rc"
printf '%s\n' DIAGNOSTICS_RC_END
exit 0
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        build_state = section(text, "BUILD_STATE_BEGIN", "BUILD_STATE_END").strip()
        version_rc = section(text, "VERSION_RC_BEGIN", "VERSION_RC_END").strip()
        version_text = section(text, "VERSION_BEGIN", "VERSION_END")
        diagnostics_rc = section(
            text, "DIAGNOSTICS_RC_BEGIN", "DIAGNOSTICS_RC_END"
        ).strip()
        diagnostics = section(text, "DIAGNOSTICS_BEGIN", "DIAGNOSTICS_END")
        locale_lines = [
            line for line in diagnostics.splitlines() if "user.language" in line
        ]
        ant_lines = [line for line in diagnostics.splitlines() if "Apache Ant" in line]
        assert_that(build_state).described_as(
            f"expected no build.xml; observed state {build_state!r}"
        ).is_equal_to("absent")
        assert_that(version_rc).described_as(
            f"expected ant -version rc 0; observed {version_rc!r}"
        ).is_equal_to("0")
        assert_that(version_text).described_as(
            f"expected Apache Ant identification; observed {version_text!r}"
        ).contains("Apache Ant")
        assert_that(diagnostics_rc).described_as(
            f"expected ant -diagnostics rc 0; observed {diagnostics_rc!r}"
        ).is_equal_to("0")
        assert_that(ant_lines).described_as(
            f"expected Ant identity in diagnostics; observed {ant_lines!r}"
        ).is_not_empty()
        assert_that(locale_lines).described_as(
            f"expected locale diagnostics; observed {locale_lines!r}"
        ).is_not_empty()

    @TestCaseMetadata(
        description="""
            Verifies Ant file-management tasks preserve newer destinations unless
            overwrite is requested, expand defined filter tokens, and retain unmatched
            tokens. It also verifies deletion and copy errors fail by default, and
            checksums are generated only for selected files and detect later corruption.

            Corpus obligation: pkg:ant/manage-project-files
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_manage_project_files(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        script = r"""tmp=$(mktemp -d -t ant-files.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/src" "$tmp/dst" "$tmp/checksums"
printf '%s\n' 'source-content' > "$tmp/src/current.txt"
printf '%s\n' 'newer-destination' > "$tmp/dst/current.txt"
touch -t 202001010000 "$tmp/src/current.txt"
touch -t 202101010000 "$tmp/dst/current.txt"
printf '%s\n' 'defined=@DEFINED@' > "$tmp/src/template.txt"
printf '%s\n' 'unmatched=@UNMATCHED@' >> "$tmp/src/template.txt"
printf '%s\n' 'checksum-one' > "$tmp/src/sum-one.txt"
printf '%s\n' 'checksum-two' > "$tmp/src/sum-two.txt"
printf '%s\n' 'not-selected' > "$tmp/src/ignored.txt"
printf '%s\n' 'remove-me' > "$tmp/obsolete.txt"
cat <<'XML' > "$tmp/build.xml"
<project name="file-management" default="file-management" basedir=".">
  <target name="file-management">
    <copy file="src/current.txt" tofile="dst/current.txt"/>
    <copy file="src/template.txt" tofile="dst/filtered.txt">
      <filterset>
        <filter token="DEFINED" value="expanded"/>
      </filterset>
    </copy>
    <delete file="obsolete.txt"/>
    <mkdir dir="checksums"/>
    <checksum todir="checksums" algorithm="SHA-256" fileext=".sha256">
      <fileset dir="src" includes="sum-one.txt,sum-two.txt"/>
    </checksum>
  </target>
  <target name="overwrite">
    <copy file="src/current.txt" tofile="dst/current.txt" overwrite="true"/>
  </target>
  <target name="verify-checksums">
    <checksum todir="checksums" algorithm="SHA-256" fileext=".sha256"
              verifyproperty="checksum.ok">
      <fileset dir="src" includes="sum-one.txt,sum-two.txt"/>
    </checksum>
    <echo message="CHECKSUM_OK=${checksum.ok}"/>
    <fail message="selected-file checksum verification failed">
      <condition>
        <not>
          <equals arg1="${checksum.ok}" arg2="true"/>
        </not>
      </condition>
    </fail>
  </target>
  <target name="copy-error">
    <copy file="src/missing.txt" tofile="dst/missing.txt"/>
  </target>
  <target name="delete-error">
    <delete file="/proc/self/status"/>
  </target>
</project>
XML
if [ -s "$tmp/build.xml" ]; then
    build_nonempty=yes
else
    build_nonempty=no
fi
main_log=$(cd "$tmp" && ant -f build.xml file-management 2>&1)
main_rc=$?
if [ -f "$tmp/dst/current.txt" ]; then
    skip_value=$(cat "$tmp/dst/current.txt")
else
    skip_value=MISSING
fi
if [ -f "$tmp/dst/filtered.txt" ]; then
    filter_value=$(cat "$tmp/dst/filtered.txt")
else
    filter_value=MISSING
fi
if [ -e "$tmp/obsolete.txt" ]; then
    obsolete_state=PRESENT
else
    obsolete_state=ABSENT
fi
if [ -s "$tmp/checksums/sum-one.txt.sha256" ]; then
    checksum_one=NONEMPTY
else
    checksum_one=MISSING
fi
if [ -s "$tmp/checksums/sum-two.txt.sha256" ]; then
    checksum_two=NONEMPTY
else
    checksum_two=MISSING
fi
if [ -e "$tmp/checksums/ignored.txt.sha256" ]; then
    checksum_ignored=PRESENT
else
    checksum_ignored=ABSENT
fi
verify_log=$(cd "$tmp" && ant -f build.xml verify-checksums 2>&1)
verify_rc=$?
overwrite_log=$(cd "$tmp" && ant -f build.xml overwrite 2>&1)
overwrite_rc=$?
if [ -f "$tmp/dst/current.txt" ]; then
    overwrite_value=$(cat "$tmp/dst/current.txt")
else
    overwrite_value=MISSING
fi
printf '%s\n' 'corrupted' > "$tmp/src/sum-one.txt"
bad_log=$(cd "$tmp" && ant -f build.xml verify-checksums 2>&1)
bad_rc=$?
copy_log=$(cd "$tmp" && ant -f build.xml copy-error 2>&1)
copy_rc=$?
delete_log=$(cd "$tmp" && ant -f build.xml delete-error 2>&1)
delete_rc=$?
if [ "$bad_rc" -ne 0 ]; then bad_failed=yes; else bad_failed=no; fi
if [ "$copy_rc" -ne 0 ]; then copy_failed=yes; else copy_failed=no; fi
if [ "$delete_rc" -ne 0 ]; then delete_failed=yes; else delete_failed=no; fi
printf '%s\n' STATUS_BEGIN
printf 'BUILD_NONEMPTY=%s\n' "$build_nonempty"
printf 'MAIN_RC=%s\n' "$main_rc"
printf 'VERIFY_RC=%s\n' "$verify_rc"
printf 'OVERWRITE_RC=%s\n' "$overwrite_rc"
printf 'BAD_CHECKSUM_FAILED=%s\n' "$bad_failed"
printf 'COPY_FAILED=%s\n' "$copy_failed"
printf 'DELETE_FAILED=%s\n' "$delete_failed"
printf '%s\n' STATUS_END
printf '%s\n%s\n%s\n' SKIP_BEGIN "$skip_value" SKIP_END
printf '%s\n%s\n%s\n' FILTER_BEGIN "$filter_value" FILTER_END
printf '%s\n%s\n%s\n' OVERWRITE_BEGIN "$overwrite_value" OVERWRITE_END
printf '%s\n' FILE_STATE_BEGIN
printf 'OBSOLETE=%s\n' "$obsolete_state"
printf 'SUM_ONE=%s\n' "$checksum_one"
printf 'SUM_TWO=%s\n' "$checksum_two"
printf 'IGNORED=%s\n' "$checksum_ignored"
printf '%s\n' FILE_STATE_END
printf '%s\n%s\n%s\n' MAIN_LOG_BEGIN "$main_log" MAIN_LOG_END
printf '%s\n%s\n%s\n' VERIFY_LOG_BEGIN "$verify_log" VERIFY_LOG_END
printf '%s\n%s\n%s\n' BAD_LOG_BEGIN "$bad_log" BAD_LOG_END
printf '%s\n%s\n%s\n' COPY_LOG_BEGIN "$copy_log" COPY_LOG_END
printf '%s\n%s\n%s\n' DELETE_LOG_BEGIN "$delete_log" DELETE_LOG_END
printf '%s\n' SCRIPT_DONE
exit 0
"""
        result = node.execute(f"{script}", shell=True)
        text = combined_output(result)
        assert_that(result.exit_code).described_as(
            f"guest file-management probe exited {result.exit_code}:\n{text}"
        ).is_equal_to(0)
        assert_that(text).described_as(
            f"guest probe did not finish; observed:\n{text}"
        ).contains("SCRIPT_DONE")
        status = section(text, "STATUS_BEGIN", "STATUS_END")
        main_log = section(text, "MAIN_LOG_BEGIN", "MAIN_LOG_END")
        verify_log = section(text, "VERIFY_LOG_BEGIN", "VERIFY_LOG_END")
        bad_log = section(text, "BAD_LOG_BEGIN", "BAD_LOG_END")
        copy_log = section(text, "COPY_LOG_BEGIN", "COPY_LOG_END")
        delete_log = section(text, "DELETE_LOG_BEGIN", "DELETE_LOG_END")
        assert_that(status).described_as(
            f"build.xml must be non-empty; observed:\n{status}"
        ).contains("BUILD_NONEMPTY=yes")
        assert_that(status).described_as(
            f"file-management target failed:\n{main_log}"
        ).contains("MAIN_RC=0")
        assert_that(status).described_as(
            f"valid checksum verification failed:\n{verify_log}"
        ).contains("VERIFY_RC=0")
        assert_that(status).described_as(
            f"overwrite target failed; observed:\n{status}"
        ).contains("OVERWRITE_RC=0")
        skip_lines = section_lines(text, "SKIP_BEGIN", "SKIP_END")
        assert_that(skip_lines).described_as(
            f"current destination must be preserved; observed {skip_lines}"
        ).is_equal_to(["newer-destination"])
        overwrite_lines = section_lines(text, "OVERWRITE_BEGIN", "OVERWRITE_END")
        assert_that(overwrite_lines).described_as(
            f"overwrite must replace the destination; observed {overwrite_lines}"
        ).is_equal_to(["source-content"])
        filter_lines = section_lines(text, "FILTER_BEGIN", "FILTER_END")
        assert_that(filter_lines).described_as(
            f"defined and unmatched token results were {filter_lines}"
        ).is_equal_to(["defined=expanded", "unmatched=@UNMATCHED@"])
        states = section_lines(text, "FILE_STATE_BEGIN", "FILE_STATE_END")
        assert_that(states).described_as(
            f"delete task left the obsolete file; observed {states}"
        ).contains("OBSOLETE=ABSENT")
        assert_that(states).described_as(
            f"first selected checksum was not generated; observed {states}"
        ).contains("SUM_ONE=NONEMPTY")
        assert_that(states).described_as(
            f"second selected checksum was not generated; observed {states}"
        ).contains("SUM_TWO=NONEMPTY")
        assert_that(states).described_as(
            f"an unselected checksum was generated; observed {states}"
        ).contains("IGNORED=ABSENT")
        assert_that(status).described_as(
            f"corrupted checksum was accepted:\n{bad_log}"
        ).contains("BAD_CHECKSUM_FAILED=yes")
        assert_that(status).described_as(
            f"missing-source copy did not fail by default:\n{copy_log}"
        ).contains("COPY_FAILED=yes")
        assert_that(status).described_as(
            f"undeletable-file removal did not fail by default:\n{delete_log}"
        ).contains("DELETE_FAILED=yes")

    @TestCaseMetadata(
        description="""
            Verifies that Ant runs shared prerequisite targets first and at most once.
            It also checks property-based target conditions, task-value expansion, and
            command-line property precedence over build-file values.

            Corpus obligation: pkg:ant/orchestrate-targets
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_orchestrate_targets(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        cli_choice = "cli"
        cli_value = "passed"
        build_value = "built"
        build_xml = rf"""<project name="orchestrate" default="main">
    <property name="choice" value="build-file"/>
    <property name="build.value" value="{build_value}"/>
    <property name="build.flag" value="yes"/>

    <target name="prereq">
        <echo file="trace.txt" append="true"
            message="prereq&#10;"/>
    </target>

    <target name="left" depends="prereq">
        <echo file="trace.txt" append="true"
            message="left:&#36;{{choice}}&#10;"/>
    </target>

    <target name="right" depends="prereq">
        <echo file="trace.txt" append="true"
            message="right:&#36;{{build.value}}&#10;"/>
    </target>

    <target name="if-build" if="build.flag">
        <echo file="trace.txt" append="true"
            message="if-build&#10;"/>
    </target>

    <target name="unless-missing" unless="missing.flag">
        <echo file="trace.txt" append="true"
            message="unless-missing&#10;"/>
    </target>

    <target name="if-missing" if="missing.flag">
        <echo file="trace.txt" append="true"
            message="UNEXPECTED_IF_MISSING&#10;"/>
    </target>

    <target name="unless-cli" unless="cli.flag">
        <echo file="trace.txt" append="true"
            message="UNEXPECTED_UNLESS_CLI&#10;"/>
    </target>

    <target name="main"
        depends="left,right,if-build,unless-missing,if-missing,unless-cli">
        <echo file="trace.txt" append="true"
            message="main:&#36;{{cli.value}}&#10;"/>
    </target>
</project>"""
        command = rf"""set -u
tmp=$(mktemp -d)
cleanup() {{ rm -rf "$tmp"; }}
trap cleanup EXIT
cat <<'XML' > "$tmp/build.xml"
{build_xml}
XML
ant -f "$tmp/build.xml" -Dchoice="{cli_choice}" \
    -Dcli.value="{cli_value}" -Dcli.flag=yes main \
    > "$tmp/ant.log" 2>&1
rc=$?
printf '%s\n' STATUS_BEGIN
printf 'ANT_RC=%s\n' "$rc"
printf '%s\n' STATUS_END
printf '%s\n' TRACE_BEGIN
if [ -f "$tmp/trace.txt" ]; then
    cat "$tmp/trace.txt"
else
    printf '%s\n' MISSING
fi
printf '%s\n' TRACE_END
printf '%s\n' ANT_OUTPUT_BEGIN
cat "$tmp/ant.log"
printf '%s\n' ANT_OUTPUT_END
exit 0
"""
        result = node.execute(command, shell=True)
        assert_that(result.exit_code).described_as(
            "the guest-side Ant probe must complete"
        ).is_equal_to(0)
        text = combined_output(result)
        status = section(text, "STATUS_BEGIN", "STATUS_END").strip()
        ant_text = section(text, "ANT_OUTPUT_BEGIN", "ANT_OUTPUT_END")
        assert_that(status).described_as(
            f"Ant must succeed; observed output was:\n{ant_text}"
        ).is_equal_to("ANT_RC=0")
        evidence = section_lines(text, "TRACE_BEGIN", "TRACE_END")
        assert_that(evidence).described_as(
            f"the trace must contain six target effects; observed {evidence}"
        ).is_length(6)
        assert_that(evidence[0]).described_as(
            f"the prerequisite must run first; observed {evidence}"
        ).is_equal_to("prereq")
        assert_that(evidence.count("prereq")).described_as(
            f"the shared prerequisite must run once; observed {evidence}"
        ).is_equal_to(1)
        assert_that(evidence[1]).described_as(
            f"the first dependent must use the CLI value; observed {evidence}"
        ).is_equal_to(f"left:{cli_choice}")
        assert_that(evidence[2]).described_as(
            f"the second dependent must expand its property; observed {evidence}"
        ).is_equal_to(f"right:{build_value}")
        assert_that(evidence).described_as(
            f"the build-property if target must run; observed {evidence}"
        ).contains("if-build")
        assert_that(evidence).described_as(
            f"the absent-property unless target must run; observed {evidence}"
        ).contains("unless-missing")
        assert_that(evidence).described_as(
            f"the absent-property if target must not run; observed {evidence}"
        ).does_not_contain("UNEXPECTED_IF_MISSING")
        assert_that(evidence).described_as(
            f"the set-property unless target must not run; observed {evidence}"
        ).does_not_contain("UNEXPECTED_UNLESS_CLI")
        assert_that(evidence[-1]).described_as(
            f"the requested target must run last; observed {evidence}"
        ).is_equal_to(f"main:{cli_value}")

    @TestCaseMetadata(
        description="""
            This case runs an Ant archive target that selects text files and creates a
            JAR without a project-supplied manifest. It verifies initial creation,
            incremental update with changed and added files, exclusion of an unselected
            file, and generation of a basic manifest.

            Corpus obligation: pkg:ant/produce-project-artifacts
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_produce_project_artifacts(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        initial_body = "first-version"
        updated_body = "second-version"
        added_body = "added-file"
        archive_member = "api/guide.txt"
        added_member = "api/added.txt"
        excluded_member = "api/private.bin"
        manifest_entry = "META-INF/MANIFEST.MF"
        manifest_token = "Manifest-Version: 1.0"
        checker = r"""
import sys
import zipfile

path = sys.argv[1]
primary_name = sys.argv[2]
primary_expected = sys.argv[3]
added_name = sys.argv[4]
added_expected = sys.argv[5]
excluded_name = sys.argv[6]
manifest_name = sys.argv[7]
manifest_token = sys.argv[8]
try:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        manifest = archive.read(manifest_name).decode("utf-8", "replace")
        primary = archive.read(primary_name).decode("utf-8", "replace")
        if added_name in names:
            added = archive.read(added_name).decode("utf-8", "replace")
        else:
            added = "MISSING"
    print("OPEN=1")
    print("PRIMARY_OK=" + str(int(primary.strip() == primary_expected)))
    print("ADDED_PRESENT=" + str(int(added_name in names)))
    print("ADDED_OK=" + str(int(added.strip() == added_expected)))
    print("EXCLUDED_PRESENT=" + str(int(excluded_name in names)))
    print("MANIFEST_OK=" + str(int(manifest_token in manifest)))
    print("NAMES=" + ",".join(names))
    print("PRIMARY_TEXT=" + repr(primary))
    print("ADDED_TEXT=" + repr(added))
    print("MANIFEST_TEXT=" + repr(manifest))
except Exception as error:
    print("OPEN=0")
    print("PRIMARY_OK=MISSING")
    print("ADDED_PRESENT=MISSING")
    print("ADDED_OK=MISSING")
    print("EXCLUDED_PRESENT=MISSING")
    print("MANIFEST_OK=MISSING")
    print("ERROR=" + type(error).__name__ + ": " + str(error))
"""
        command = rf"""
tmp=$(mktemp -d /tmp/ant-artifact.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/src/api"
printf '%s\n' '{initial_body}' > "$tmp/src/{archive_member}"
printf '%s\n' 'not-selected' > "$tmp/src/{excluded_member}"
cat <<'XML' > "$tmp/build.xml"
<project name="artifact-probe" default="archive">
  <target name="archive">
    <mkdir dir="out"/>
    <jar destfile="out/project.jar" basedir="src" includes="**/*.txt"/>
  </target>
</project>
XML
cat <<'PY' > "$tmp/checker.py"
{checker}
PY
echo INFO_BEGIN
rpm -q --qf '%{{NAME}} %{{VERSION}}-%{{RELEASE}}\n' ant
printf 'RPM_RC=%s\n' "$?"
ant -version
printf 'ANT_VERSION_RC=%s\n' "$?"
echo INFO_END
echo FIRST_BEGIN
ant -f "$tmp/build.xml" archive
printf 'FIRST_ANT_RC=%s\n' "$?"
if test -f "$tmp/out/project.jar"; then
    echo FIRST_ARCHIVE=present
else
    echo FIRST_ARCHIVE=absent
fi
if test -s "$tmp/checker.py"; then
    echo CHECKER_READY=1
    python3 "$tmp/checker.py" "$tmp/out/project.jar" \
        '{archive_member}' '{initial_body}' \
        '{added_member}' '{added_body}' \
        '{excluded_member}' '{manifest_entry}' '{manifest_token}'
    printf 'FIRST_CHECK_RC=%s\n' "$?"
else
    echo CHECKER_READY=0
    echo OPEN=MISSING
    echo PRIMARY_OK=MISSING
    echo ADDED_PRESENT=MISSING
    echo ADDED_OK=MISSING
    echo EXCLUDED_PRESENT=MISSING
    echo MANIFEST_OK=MISSING
    echo FIRST_CHECK_RC=125
fi
echo FIRST_END
sleep 2
printf '%s\n' '{updated_body}' > "$tmp/src/{archive_member}"
printf '%s\n' '{added_body}' > "$tmp/src/{added_member}"
echo SECOND_BEGIN
ant -f "$tmp/build.xml" archive
printf 'SECOND_ANT_RC=%s\n' "$?"
if test -f "$tmp/out/project.jar"; then
    echo SECOND_ARCHIVE=present
else
    echo SECOND_ARCHIVE=absent
fi
if test -s "$tmp/checker.py"; then
    echo CHECKER_READY=1
    python3 "$tmp/checker.py" "$tmp/out/project.jar" \
        '{archive_member}' '{updated_body}' \
        '{added_member}' '{added_body}' \
        '{excluded_member}' '{manifest_entry}' '{manifest_token}'
    printf 'SECOND_CHECK_RC=%s\n' "$?"
else
    echo CHECKER_READY=0
    echo OPEN=MISSING
    echo PRIMARY_OK=MISSING
    echo ADDED_PRESENT=MISSING
    echo ADDED_OK=MISSING
    echo EXCLUDED_PRESENT=MISSING
    echo MANIFEST_OK=MISSING
    echo SECOND_CHECK_RC=125
fi
echo SECOND_END
exit 0
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        assert_that(result.exit_code).described_as(
            f"artifact probe shell must complete; observed output: {text}"
        ).is_equal_to(0)
        info = section(text, "INFO_BEGIN", "INFO_END")
        assert_that(info).described_as(
            f"installed Ant package query must succeed; observed: {info}"
        ).contains("RPM_RC=0")
        assert_that(info).described_as(
            f"Ant executable must start successfully; observed: {info}"
        ).contains("ANT_VERSION_RC=0")
        first = section(text, "FIRST_BEGIN", "FIRST_END")
        assert_that(first).described_as(
            f"initial Ant archive target must succeed; observed: {first}"
        ).contains("FIRST_ANT_RC=0")
        assert_that(first).described_as(
            f"initial archive must be created; observed: {first}"
        ).contains("FIRST_ARCHIVE=present")
        assert_that(first).described_as(
            f"archive checker must be materialized; observed: {first}"
        ).contains("CHECKER_READY=1")
        assert_that(first).described_as(
            f"initial archive must be readable; observed: {first}"
        ).contains("OPEN=1")
        assert_that(first).described_as(
            f"initial selected file must have expected content; observed: {first}"
        ).contains("PRIMARY_OK=1")
        assert_that(first).described_as(
            f"future selected file must initially be absent; observed: {first}"
        ).contains("ADDED_PRESENT=0")
        assert_that(first).described_as(
            f"unselected file must not be archived; observed: {first}"
        ).contains("EXCLUDED_PRESENT=0")
        assert_that(first).described_as(
            f"Ant must supply a basic manifest; observed: {first}"
        ).contains("MANIFEST_OK=1")
        assert_that(first).described_as(
            f"initial archive inspection must complete; observed: {first}"
        ).contains("FIRST_CHECK_RC=0")
        second = section(text, "SECOND_BEGIN", "SECOND_END")
        assert_that(second).described_as(
            f"archive update target must succeed; observed: {second}"
        ).contains("SECOND_ANT_RC=0")
        assert_that(second).described_as(
            f"updated archive must remain present; observed: {second}"
        ).contains("SECOND_ARCHIVE=present")
        assert_that(second).described_as(
            f"updated archive must be readable; observed: {second}"
        ).contains("OPEN=1")
        assert_that(second).described_as(
            f"changed selected content must update in the JAR; observed: {second}"
        ).contains("PRIMARY_OK=1")
        assert_that(second).described_as(
            f"new selected file must be added to the JAR; observed: {second}"
        ).contains("ADDED_PRESENT=1")
        assert_that(second).described_as(
            f"new archive member must retain its content; observed: {second}"
        ).contains("ADDED_OK=1")
        assert_that(second).described_as(
            f"unselected file must remain excluded; observed: {second}"
        ).contains("EXCLUDED_PRESENT=0")
        assert_that(second).described_as(
            f"updated JAR must retain its basic manifest; observed: {second}"
        ).contains("MANIFEST_OK=1")
        assert_that(second).described_as(
            f"updated archive inspection must complete; observed: {second}"
        ).contains("SECOND_CHECK_RC=0")

    @TestCaseMetadata(
        description="""
            Verifies that Ant compiles and runs a Java class in a forked JVM with
            supplied arguments and captures its output. It also verifies that
            System.exit in the application is isolated from Ant, which records the exit
            status and continues the build.

            Corpus obligation: pkg:ant/run-java-application
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_run_java_application(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        expected_arg = "azure-linux-ant-argument"
        java_source = r"""
public final class Probe {
    public static void main(String[] args) {
        if (args.length == 0) {
            System.out.println("ARG=MISSING");
            System.exit(9);
        }
        System.out.println("ARG=" + args[0]);
        if (args.length > 1 && args[1].equals("exit")) {
            System.out.println("EXITING=7");
            System.exit(7);
        }
    }
}
"""
        build_xml = rf"""
<project name="java-probe" default="verify" basedir=".">
    <target name="verify">
        <mkdir dir="classes"/>
        <javac srcdir="src" destdir="classes"
               includeantruntime="false"/>
        <java classname="Probe" fork="true" failonerror="true"
              outputproperty="normal.output">
            <classpath path="classes"/>
            <arg value="{expected_arg}"/>
            <arg value="normal"/>
        </java>
        <echo file="${{basedir}}/arg.txt"
              message="${{normal.output}}"/>
        <java classname="Probe" fork="true" failonerror="false"
              resultproperty="exit.code" outputproperty="exit.output">
            <classpath path="classes"/>
            <arg value="{expected_arg}"/>
            <arg value="exit"/>
        </java>
        <echo file="${{basedir}}/exit-output.txt"
              message="${{exit.output}}"/>
        <echo file="${{basedir}}/exit-result.txt"
              message="${{exit.code}}"/>
        <echo file="${{basedir}}/continued.txt"
              message="AFTER_EXIT"/>
    </target>
</project>
"""
        command = f"""tmp=$(mktemp -d /tmp/ant-java.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/src"
cat <<'JAVA' > "$tmp/src/Probe.java"
{java_source}
JAVA
cat <<'XML' > "$tmp/build.xml"
{build_xml}
XML
material=OK
if ! test -s "$tmp/src/Probe.java"; then
    material=MISSING_JAVA
fi
if ! test -s "$tmp/build.xml"; then
    material=MISSING_XML
fi
ant_rc=125
if [ "$material" = OK ]; then
    ant -f "$tmp/build.xml" -noinput verify > "$tmp/ant.log" 2>&1
    ant_rc=$?
else
    printf '%s\n' "$material" > "$tmp/ant.log"
fi
printf '%s\n' MATERIAL_BEGIN
printf '%s\n' "$material"
printf '%s\n' MATERIAL_END
printf '%s\n' ANT_RC_BEGIN
printf '%s\n' "$ant_rc"
printf '%s\n' ANT_RC_END
printf '%s\n' ANT_LOG_BEGIN
cat "$tmp/ant.log" 2>/dev/null || printf '%s\n' MISSING
printf '%s\n' ANT_LOG_END
printf '%s\n' ARG_OUTPUT_BEGIN
if [ -s "$tmp/arg.txt" ]; then
    value=$(cat "$tmp/arg.txt")
    printf '%s\n' "$value"
else
    printf '%s\n' MISSING
fi
printf '%s\n' ARG_OUTPUT_END
printf '%s\n' EXIT_OUTPUT_BEGIN
if [ -s "$tmp/exit-output.txt" ]; then
    value=$(cat "$tmp/exit-output.txt")
    printf '%s\n' "$value"
else
    printf '%s\n' MISSING
fi
printf '%s\n' EXIT_OUTPUT_END
printf '%s\n' EXIT_RESULT_BEGIN
if [ -s "$tmp/exit-result.txt" ]; then
    value=$(cat "$tmp/exit-result.txt")
    printf '%s\n' "$value"
else
    printf '%s\n' MISSING
fi
printf '%s\n' EXIT_RESULT_END
printf '%s\n' CONTINUED_BEGIN
if [ -s "$tmp/continued.txt" ]; then
    value=$(cat "$tmp/continued.txt")
    printf '%s\n' "$value"
else
    printf '%s\n' MISSING
fi
printf '%s\n' CONTINUED_END
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        material = section_lines(text, "MATERIAL_BEGIN", "MATERIAL_END")
        ant_rc = section_lines(text, "ANT_RC_BEGIN", "ANT_RC_END")
        ant_log = section(text, "ANT_LOG_BEGIN", "ANT_LOG_END")
        arg_lines = section_lines(text, "ARG_OUTPUT_BEGIN", "ARG_OUTPUT_END")
        exit_lines = section_lines(text, "EXIT_OUTPUT_BEGIN", "EXIT_OUTPUT_END")
        exit_result = section_lines(text, "EXIT_RESULT_BEGIN", "EXIT_RESULT_END")
        continued = section_lines(text, "CONTINUED_BEGIN", "CONTINUED_END")
        assert_that(result.exit_code).described_as(
            f"guest probe rc was {result.exit_code}, expected 0"
        ).is_equal_to(0)
        assert_that(material).described_as(
            f"materialization was {material!r}, expected OK"
        ).is_equal_to(["OK"])
        assert_that(ant_rc).described_as(
            f"Ant build rc was {ant_rc!r}, log was {ant_log!r}"
        ).is_equal_to(["0"])
        assert_that(arg_lines).described_as(
            f"captured application output was {arg_lines!r}"
        ).contains(f"ARG={expected_arg}")
        assert_that(exit_lines).described_as(
            f"forked exit output was {exit_lines!r}"
        ).contains(f"ARG={expected_arg}")
        assert_that(exit_lines).described_as(
            f"forked exit output was {exit_lines!r}"
        ).contains("EXITING=7")
        assert_that(exit_result).described_as(
            f"forked JVM result was {exit_result!r}, expected 7"
        ).is_equal_to(["7"])
        assert_that(continued).described_as(
            f"post-exit build marker was {continued!r}"
        ).is_equal_to(["AFTER_EXIT"])

    @TestCaseMetadata(
        description="""
            Runs a self-contained Ant project's test target with two selected tests that
            exercise file copying, property loading, conditions, and failure handling.
            It verifies that both tests execute, report their outcomes, create the
            expected evidence, and complete successfully.

            Corpus obligation: pkg:ant/run-project-tests
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_run_project_tests(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        copy_marker = "CASE_COPY_EXECUTED"
        selection_marker = "CASE_SELECTION_EXECUTED"
        summary_marker = "TESTS_RUN=2 FAILURES=0 ERRORS=0"
        project = rf"""
<project name="project-tests" default="test">
    <property name="work" location="${{basedir}}/out"/>
    <target name="init">
        <delete dir="${{work}}" quiet="true"/>
        <mkdir dir="${{work}}"/>
        <echo file="${{work}}/source.txt">alpha-beta</echo>
    </target>
    <target name="test-copy-roundtrip" depends="init">
        <copy file="${{work}}/source.txt"
              tofile="${{work}}/copied.txt"/>
        <loadfile property="copied.text"
                  srcfile="${{work}}/copied.txt"/>
        <condition property="copy.ok">
            <equals arg1="${{copied.text}}" arg2="alpha-beta"/>
        </condition>
        <fail unless="copy.ok" message="copy roundtrip failed"/>
        <echo file="${{work}}/copy.ok">passed</echo>
        <echo message="{copy_marker}"/>
    </target>
    <target name="test-selection" depends="test-copy-roundtrip">
        <condition property="selection.ok">
            <and>
                <isset property="copy.ok"/>
                <available file="${{work}}/copied.txt" type="file"/>
            </and>
        </condition>
        <fail unless="selection.ok" message="selected test failed"/>
        <echo file="${{work}}/selection.ok">passed</echo>
        <echo message="{selection_marker}"/>
    </target>
    <target name="test"
            depends="test-copy-roundtrip,test-selection">
        <echo message="{summary_marker}"/>
    </target>
</project>
"""
        command = rf"""
tmp=$(mktemp -d /tmp/ant-project-tests.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cat <<'XML' > "$tmp/build.xml"
{project}
XML
rpm -q --qf '%{{NAME}} %{{VERSION}}-%{{RELEASE}}\n' ant \
    > "$tmp/rpm.log" 2>&1
rpm_rc=$?
ant -version > "$tmp/version.log" 2>&1
version_rc=$?
ant -f "$tmp/build.xml" test > "$tmp/ant.log" 2>&1
ant_rc=$?
if test -f "$tmp/out/copied.txt"; then
    copy_exists=yes
else
    copy_exists=no
fi
if test -f "$tmp/out/copy.ok"; then
    copy_test_exists=yes
else
    copy_test_exists=no
fi
if test -f "$tmp/out/selection.ok"; then
    selection_test_exists=yes
else
    selection_test_exists=no
fi
printf '%s\n' PKG_BEGIN
printf 'RPM_RC=%s\n' "$rpm_rc"
cat "$tmp/rpm.log" 2>/dev/null || printf '%s\n' MISSING
printf 'VERSION_RC=%s\n' "$version_rc"
cat "$tmp/version.log" 2>/dev/null || printf '%s\n' MISSING
printf '%s\n' PKG_END
printf '%s\n' ANT_LOG_BEGIN
cat "$tmp/ant.log" 2>/dev/null || printf '%s\n' MISSING
printf '%s\n' ANT_LOG_END
printf '%s\n' FACTS_BEGIN
printf 'ANT_RC=%s\n' "$ant_rc"
printf 'COPY_EXISTS=%s\n' "$copy_exists"
printf 'COPY_TEST_EXISTS=%s\n' "$copy_test_exists"
printf 'SELECTION_TEST_EXISTS=%s\n' "$selection_test_exists"
printf '%s\n' FACTS_END
printf '%s\n' COPY_BODY_BEGIN
if test -f "$tmp/out/copied.txt"; then
    cat "$tmp/out/copied.txt"
else
    printf '%s' MISSING
fi
printf '\n%s\n' COPY_BODY_END
exit "$ant_rc"
"""
        result = node.execute(command, shell=True)
        text = combined_output(result)
        package_text = section(text, "PKG_BEGIN", "PKG_END")
        ant_log = section(text, "ANT_LOG_BEGIN", "ANT_LOG_END")
        fact_lines = section_lines(text, "FACTS_BEGIN", "FACTS_END")
        copy_body = section(text, "COPY_BODY_BEGIN", "COPY_BODY_END")
        assert_that(package_text).described_as(
            f"Ant package evidence was: {package_text}"
        ).contains("RPM_RC=0")
        assert_that(package_text).described_as(
            f"Ant version evidence was: {package_text}"
        ).contains("VERSION_RC=0")
        assert_that(package_text).described_as(
            f"Installed Ant package details were: {package_text}"
        ).contains("ant ")
        assert_that(result.exit_code).described_as(
            f"Ant test target rc was {result.exit_code}; log: {ant_log}"
        ).is_equal_to(0)
        assert_that(fact_lines).described_as(
            f"Project execution facts were {fact_lines}"
        ).contains("ANT_RC=0")
        assert_that(ant_log).described_as(
            f"Copy test activity was absent from log: {ant_log}"
        ).contains(copy_marker)
        assert_that(ant_log).described_as(
            f"Selection test activity was absent from log: {ant_log}"
        ).contains(selection_marker)
        assert_that(ant_log).described_as(
            f"Test outcome summary was absent from log: {ant_log}"
        ).contains(summary_marker)
        assert_that(fact_lines).described_as(
            f"Copy output evidence was {fact_lines}"
        ).contains("COPY_EXISTS=yes")
        assert_that(fact_lines).described_as(
            f"Copy test outcome evidence was {fact_lines}"
        ).contains("COPY_TEST_EXISTS=yes")
        assert_that(fact_lines).described_as(
            f"Selection test outcome evidence was {fact_lines}"
        ).contains("SELECTION_TEST_EXISTS=yes")
        assert_that(copy_body).described_as(
            f"Copied content was {copy_body!r}, expected alpha-beta"
        ).is_equal_to("alpha-beta")

    @TestCaseMetadata(
        description="""
            Verifies that Ant uses the default Java runtime when no override is present.
            It also verifies that JAVA_HOME from the environment or the user's ant.conf
            selects the configured launcher while preserving its output and exit status.

            Corpus obligation: pkg:ant/select-java-runtime
        """,
        priority=3,
        tags=["ai-generated"],
    )
    def verify_select_java_runtime(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "4.0.0":
            raise SkippedException(
                "this case is derived from an Azure Linux 4.0 corpus and was verified"
                " only on Azure Linux 4.0.0 guests; this node reports "
                f"{node.os.information.version}"
            )

        default_marker = "DEFAULT_JAVA_ANT_RAN"
        env_stdout = "ENV_JAVA_STDOUT"
        env_stderr = "ENV_JAVA_STDERR"
        conf_stdout = "CONF_JAVA_STDOUT"
        conf_stderr = "CONF_JAVA_STDERR"
        env_rc = 37
        conf_rc = 41
        script = rf"""
tmp=$(mktemp -d /tmp/ant-java-runtime.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/default-home"
mkdir -p "$tmp/env-home" "$tmp/env-java/bin"
mkdir -p "$tmp/conf-home/.ant" "$tmp/conf-java/bin"
cat <<'XML' > "$tmp/build.xml"
<project default="verify">
  <target name="verify">
    <echo message="{default_marker}"/>
  </target>
</project>
XML
cat <<'SH' > "$tmp/env-java/bin/java"
#!/bin/sh
printf '%s\n' '{env_stdout}'
printf '%s\n' '{env_stderr}' >&2
exit {env_rc}
SH
cat <<'SH' > "$tmp/conf-java/bin/java"
#!/bin/sh
printf '%s\n' '{conf_stdout}'
printf '%s\n' '{conf_stderr}' >&2
exit {conf_rc}
SH
chmod +x "$tmp/env-java/bin/java"
chmod +x "$tmp/conf-java/bin/java"
printf '%s\n' 'JAVA_HOME="$HOME/../conf-java"' \
    'export JAVA_HOME' > "$tmp/conf-home/.ant/ant.conf"
helpers=ready
[ -s "$tmp/build.xml" ] || helpers=not-ready
[ -s "$tmp/env-java/bin/java" ] || helpers=not-ready
[ -x "$tmp/env-java/bin/java" ] || helpers=not-ready
[ -s "$tmp/conf-java/bin/java" ] || helpers=not-ready
[ -x "$tmp/conf-java/bin/java" ] || helpers=not-ready
[ -s "$tmp/conf-home/.ant/ant.conf" ] || helpers=not-ready
printf '%s\n' SETUP_BEGIN
if [ "$helpers" = ready ]; then
    printf '%s\n' 'HELPERS=ready'
else
    printf '%s\n' 'FIXTURE_NOT_READY=helpers'
fi
printf '%s\n' SETUP_END
printf '%s\n' DEFAULT_BEGIN
(
    unset JAVA_HOME JAVACMD
    HOME="$tmp/default-home"
    export HOME
    ant -f "$tmp/build.xml" verify
)
default_rc=$?
printf 'RC=%s\n' "$default_rc"
printf '%s\n' DEFAULT_END
printf '%s\n' ENV_BEGIN
(
    unset JAVACMD
    HOME="$tmp/env-home"
    JAVA_HOME="$tmp/env-java"
    export HOME JAVA_HOME
    ant -f "$tmp/build.xml" verify
)
env_status=$?
printf 'RC=%s\n' "$env_status"
printf '%s\n' ENV_END
printf '%s\n' CONF_BEGIN
(
    unset JAVA_HOME JAVACMD
    HOME="$tmp/conf-home"
    export HOME
    ant -f "$tmp/build.xml" verify
)
conf_status=$?
printf 'RC=%s\n' "$conf_status"
printf '%s\n' CONF_END
exit 0
"""
        result = node.execute(script, shell=True)
        assert_that(result.exit_code).described_as(
            f"runtime probe script exit code was {result.exit_code}"
        ).is_equal_to(0)
        text = combined_output(result)
        setup_text = section(text, "SETUP_BEGIN", "SETUP_END")
        if "HELPERS=ready" not in setup_text:
            raise SkippedException(
                f"Java launcher fixtures were not ready: {setup_text}"
            )
        default_text = section(text, "DEFAULT_BEGIN", "DEFAULT_END")
        env_text = section(text, "ENV_BEGIN", "ENV_END")
        conf_text = section(text, "CONF_BEGIN", "CONF_END")
        assert_that(default_text).described_as(
            f"default Java Ant evidence: {default_text}"
        ).contains(default_marker)
        assert_that(default_text).described_as(
            f"default Java Ant exit evidence: {default_text}"
        ).contains("RC=0")
        assert_that(default_text).described_as(
            f"default Java unexpectedly used an override: {default_text}"
        ).does_not_contain(env_stdout)
        assert_that(default_text).described_as(
            f"default Java unexpectedly used ant.conf: {default_text}"
        ).does_not_contain(conf_stdout)
        assert_that(env_text).described_as(
            f"JAVA_HOME stdout evidence: {env_text}"
        ).contains(env_stdout)
        assert_that(env_text).described_as(
            f"JAVA_HOME stderr evidence: {env_text}"
        ).contains(env_stderr)
        assert_that(env_text).described_as(
            f"JAVA_HOME exit evidence: {env_text}"
        ).contains(f"RC={env_rc}")
        assert_that(conf_text).described_as(
            f"ant.conf stdout evidence: {conf_text}"
        ).contains(conf_stdout)
        assert_that(conf_text).described_as(
            f"ant.conf stderr evidence: {conf_text}"
        ).contains(conf_stderr)
        assert_that(conf_text).described_as(
            f"ant.conf exit evidence: {conf_text}"
        ).contains(f"RC={conf_rc}")
