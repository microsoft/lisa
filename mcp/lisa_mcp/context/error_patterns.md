# LISA Known Error Patterns

Common errors encountered in LISA test runs, their root causes, and resolutions.

---

### TcpConnectionException

**Symptom:** `TcpConnectionException: failed to connect to <ip>:<port>`

**Root Cause:** The target node is not reachable via TCP. Common reasons:
- VM is still booting (provisioning agent hasn't started sshd yet)
- VM kernel panicked during boot
- Network Security Group (NSG) blocks port 22
- VM was deallocated or failed provisioning
- Network configuration error (wrong subnet, missing public IP)

**Resolution:**
1. Check VM status in the platform portal
2. Check serial console for boot errors or kernel panics
3. Verify NSG rules allow inbound SSH (port 22)
4. Increase `wait_resource_timeout` in runbook if VM is slow to boot
5. Check if the image requires cloud-init to complete before sshd starts

---

### SkippedException

**Symptom:** Test is marked SKIPPED instead of running

**Root Cause:** Test preconditions not met. Not a failure — working as designed.
- Target OS doesn't match `supported_os` in `simple_requirement()`
- Required feature (GPU, NVMe, SR-IOV) not available on the VM size
- Required tool not installable on the target distro
- Kernel version too old for the tested functionality

**Resolution:**
- Verify the test's `simple_requirement()` matches your target environment
- Choose a VM size that provides the required features
- Use an image/distro that supports the tested functionality

---

### BadEnvironmentStateException

**Symptom:** `BadEnvironmentStateException: environment is not in expected state`

**Root Cause:** The environment lifecycle is inconsistent — usually because:
- A previous test modified the node and didn't call `node.mark_dirty()`
- The node was rebooted but didn't come back online
- Platform-level timeout during environment recovery

**Resolution:**
1. Check if the previous test in the run modified kernel params, drivers, or network
2. Add `node.mark_dirty()` to tests that alter system state
3. Use `use_new_environment=True` for isolated test execution
4. Check platform logs for environment lifecycle errors

---

### OverconstrainedAllocationRequest

**Symptom:** Azure deployment fails with allocation constraint error

**Root Cause:** No physical host in the target region matches all the requested
VM constraints (size, zone, disk type, accelerated networking, etc.)

**Resolution:**
1. Try a different Azure region
2. Remove or relax constraints (availability zone, specific VM size)
3. Try a different VM size family with similar capabilities
4. Check Azure capacity status for the region

---

### QuotaExceeded

**Symptom:** Azure returns quota exceeded error during deployment

**Root Cause:** Subscription hit resource limits — vCPU count, VM count, or
VM family-specific quotas.

**Resolution:**
1. Clean up idle VMs and unused resources in the subscription
2. Request quota increase via Azure portal → Quotas
3. Use a different subscription
4. Reduce `concurrency` in the runbook to deploy fewer VMs simultaneously

---

### Kernel Panic / BUG: soft lockup

**Symptom:** VM becomes unresponsive; serial console shows panic or lockup

**Root Cause:** Kernel-level crash. Common triggers:
- Driver incompatibility (especially with accelerated networking or GPU)
- Memory corruption
- Incompatible kernel parameters (e.g., swiotlb, iommu settings)
- Race condition in boot sequence

**Resolution:**
1. Check serial console output for full panic trace
2. Identify the faulting module from the call trace
3. Check if the kernel version is known-good for this distro
4. If caused by custom kernel params, test without them first
5. Report to distro vendor with serial console output

---

### AssertionError / assert_that failure

**Symptom:** Test fails with assertion mismatch

**Root Cause:** The system under test produced unexpected output. This is
usually the "real" test finding a real bug.

**Resolution:**
1. Read the `.described_as()` message for business context
2. Compare expected vs actual values
3. SSH to the node manually and reproduce the command
4. Check if the behavior is distro-specific or version-specific
5. Verify test expectations match the documentation/spec

---

### PassedException

**Symptom:** Test shows as ATTEMPTED instead of PASSED

**Root Cause:** The test encountered a non-critical error but still achieved
its primary objective. It's a "soft pass" with caveats.

**Resolution:**
- Review the warning message to understand what was unexpected
- Decide if the caveat is acceptable for your validation scenario
- Consider filing a bug if the warning indicates a real issue

---

### SSH Authentication Failure

**Symptom:** `paramiko.ssh_exception.AuthenticationException`

**Root Cause:** SSH credentials don't work on the target node.
- Wrong username/password combination
- SSH key not accepted
- Password authentication disabled in sshd_config
- Cloud-init hasn't configured the user yet

**Resolution:**
1. Verify `admin_username` and `admin_private_key_file` in runbook
2. Check if the image uses key-only authentication
3. Ensure `admin_private_key_file` points to a valid key
4. Wait longer for cloud-init to complete user setup

---

### LisaException: tool not found

**Symptom:** A LISA tool can't find its underlying command on the node

**Root Cause:** The Linux command that the tool wraps isn't installed.

**Resolution:**
- The tool should auto-install via the OS package manager
- If not, the distro may not have the package in its repos
- Check if the tool's `_install` method handles the target distro
- Consider raising `SkippedException` if the tool is optional for the test
