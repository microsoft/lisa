from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.testsuite import simple_requirement

@TestSuiteMetadata(
	area="lvbs",
	category="sanity",
	description="Sanity check for LVBS enablement after boot."
)
class LVBSSanitySuite(TestSuite):
	"""
	Test suite to verify LVBS enablement after boot by checking dmesg logs.
	"""

	@TestCaseMetadata(
		description="Check dmesg for LVBS enablement after boot.",
		priority=3,
		requirement=simple_requirement(),
		timeout=300,
	)
	def verify_lvbs_enabled(self, node: Node) -> None:
		"""
		Verifies that LVBS is enabled by searching for specific strings in dmesg output.
		"""
		dmesg = node.execute("dmesg | grep heki", sudo=True, shell=True)
		output = dmesg.stdout.strip()

		assert "heki-guest: Control registers locked" in output, (
			"'heki-guest: Control registers locked' not found in dmesg output."
		)
		assert "heki-guest: Loaded kernel data" in output, (
			"'heki-guest: Loaded kernel data' not found in dmesg output."
		)
		for line in output.splitlines():
			if "Failed to validate module" in line and not any(x in line for x in ["kvm", "kvm_intel", "rapl"]):
				assert False, f"Unexpected module validation failure: {line}"
		assert "heki-guest: Failed to set memory permission" not in output, (
			"heki-guest: Failed to set memory permission found in dmesg output."
		)
