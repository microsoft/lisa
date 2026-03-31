# LISA test case template.
# Copy and modify for your test scenario.
# Location: lisa/microsoft/testsuites/<feature_area>/<test_name>.py



from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)

# Import only what you use:
# from lisa.features import Disk, NetworkInterface, SerialConsole, StartStop
# from lisa.tools import Cat, Curl, Dmesg, Lspci
# from lisa.sut_orchestrator import AZURE


@TestSuiteMetadata(
    area="<feature_area>",  # "storage", "network", "kernel", "compute"
    category="functional",  # "functional" | "performance" | "community"
    description="<What this test suite validates.>",
)
class MyFeatureTests(TestSuite):
    # Constants — always comment their purpose
    # RETRY_COUNT = 3  # retries for transient conditions

    @TestCaseMetadata(
        description="<What observable behavior this validates.>",
        priority=2,
        requirement=simple_requirement(
            # Uncomment and customize:
            # min_core_count=2,
            # supported_os=[Ubuntu, Redhat],
            # unsupported_os=[Windows],
            # supported_platform_type=[AZURE],
            # supported_features=[SerialConsole],
        ),
    )
    def verify_my_scenario(self, node: Node) -> None:
        # ===== ARRANGE =====
        # Acquire tools and features
        # my_tool = node.tools[MyTool]
        # my_feature = node.features[MyFeature]

        # Validate preconditions
        # if not some_precondition:
        #     raise SkippedException("reason")

        # ===== ACT =====
        # Minimal action to trigger behavior
        # result = my_tool.run("--check")

        # ===== ASSERT =====
        # Explicit verification
        # assert_that(result.exit_code).described_as(
        #     "command should succeed"
        # ).is_equal_to(0)
        pass

    # Cleanup if test modifies node state
    # def after_case(self, log: Logger, **kwargs: Any) -> None:
    #     ...
