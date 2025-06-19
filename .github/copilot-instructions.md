## Test Suggestions

When creating a PR, generate a test coverage suggestion plan. If the code changes impact test coverage during the PR lifecycle, update the plan accordingly. Do not include unit tests in the list, as they are included by default.

- **Select Key Test Cases:** List only the essential test cases to validate the PR. Specify the test case names as the method names, not class names or file names. When the change is not related to specific test cases, choose the test cases that can test the change. Use pipe '|' to separate names (e.g., verify_reboot_in_platform|verify_stop_start_in_platform).
- **List Impacted LISA Features:** Mention only the relevant LISA Feature classes affected by this PR. LISA Features are platform-specific capability classes (e.g., Gpu, Nvme, StartStop, Resize, NetworkInterface) that represent testable functionality and can be required by test cases.
- **List Tested Azure Marketplace Images:** For each tested image, always provide the complete image string exactly as listed below. Select only the minimal set of images necessary to validate your changes, ensuring both accuracy and cost efficiency in test coverage.

**Azure Marketplace Images:**
- canonical 0001-com-ubuntu-server-jammy 22_04-lts latest
- canonical 0001-com-ubuntu-server-jammy 22_04-lts-arm64 latest
- canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest
- canonical ubuntu-24_04-lts server latest
- canonical ubuntu-24_04-lts server-arm64 latest
- canonical ubuntu-24_04-lts server-gen1 latest
- debian debian-11 11 latest
- debian debian-11 11-gen2 latest
- debian debian-12 12 latest
- debian debian-12 12-arm64 latest
- debian debian-12 12-gen2 latest
- microsoftcblmariner azure-linux-3 azure-linux-3 latest
- microsoftcblmariner azure-linux-3 azure-linux-3-arm64 latest
- microsoftcblmariner azure-linux-3 azure-linux-3-gen2 latest
- oracle oracle-linux ol810-arm64-lvm-gen2 latest
- oracle oracle-linux ol810-lvm latest
- oracle oracle-linux ol810-lvm-gen2 latest
- oracle oracle-linux ol89-arm64-lvm-gen2 latest
- oracle oracle-linux ol89-lvm latest
- oracle oracle-linux ol89-lvm-gen2 latest
- oracle oracle-linux ol94-arm64-lvm-gen2 latest
- oracle oracle-linux ol94-lvm latest
- oracle oracle-linux ol94-lvm-gen2 latest
- redhat rhel 8_10 latest
- redhat rhel 810-gen2 latest
- redhat rhel 9_5 latest
- redhat rhel 95_gen2 latest
- redhat rhel-arm64 9_5-arm64 latest
- suse sles-12-sp5 gen1 latest
- suse sles-12-sp5 gen2 latest
- suse sles-15-sp6 gen1 latest
- suse sles-15-sp6 gen2 latest
- suse sles-15-sp6-arm64 gen2 latest
