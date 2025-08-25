# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# The file imports all the mix-in types that can be initialized
# using reflection.

import platform

import lisa.combinators.batch_combinator  # noqa: F401
import lisa.combinators.csv_combinator  # noqa: F401
import lisa.combinators.git_bisect_combinator  # noqa: F401
import lisa.combinators.grid_combinator  # noqa: F401
import lisa.notifiers.console  # noqa: F401
import lisa.notifiers.env_stats  # noqa: F401
import lisa.notifiers.file  # noqa: F401
import lisa.notifiers.html  # noqa: F401
import lisa.notifiers.junit  # noqa: F401
import lisa.notifiers.perfdump  # noqa: F401
import lisa.notifiers.text_result  # noqa: F401
import lisa.runners.lisa_runner  # noqa: F401
import lisa.sut_orchestrator.ready  # noqa: F401

# Azure modules
try:
    import lisa.sut_orchestrator.azure.hooks  # noqa: F401
    import lisa.sut_orchestrator.azure.notifiers  # noqa: F401
    import lisa.sut_orchestrator.azure.transformers  # noqa: F401
    import lisa.transformers.disable_cloud_components  # noqa: F401
    import lisa.transformers.hyperv_preparation  # noqa: F401
except ModuleNotFoundError as e:
    print(f"azure package is not installed. [{e}]")

# Baremetal modules
try:
    import lisa.sut_orchestrator.baremetal.build  # noqa: F401
    import lisa.sut_orchestrator.baremetal.cluster.cluster  # noqa: F401
    import lisa.sut_orchestrator.baremetal.cluster.idrac  # noqa: F401
    import lisa.sut_orchestrator.baremetal.cluster.pxe  # noqa: F401
    import lisa.sut_orchestrator.baremetal.cluster.rackmanager  # noqa: F401
    import lisa.sut_orchestrator.baremetal.ip_getter  # noqa: F401
    import lisa.sut_orchestrator.baremetal.platform_  # noqa: F401
    import lisa.sut_orchestrator.baremetal.readychecker  # noqa: F401
    import lisa.sut_orchestrator.baremetal.source  # noqa: F401
except ModuleNotFoundError as e:
    print(f"baremetal package is not installed. [{e}]")

# Aws modules
try:
    import lisa.sut_orchestrator.aws.platform_  # noqa: F401
except ModuleNotFoundError as e:
    print(f"aws package is not installed. [{e}]")

if platform.system() == "Linux":
    # libvirt modules
    try:
        import lisa.sut_orchestrator.libvirt.ch_platform  # noqa: F401
        import lisa.sut_orchestrator.libvirt.context  # noqa: F401
        import lisa.sut_orchestrator.libvirt.platform  # noqa: F401
        import lisa.sut_orchestrator.libvirt.qemu_platform  # noqa: F401
        import lisa.sut_orchestrator.libvirt.schema  # noqa: F401
        import lisa.sut_orchestrator.libvirt.transformers  # noqa: F401
    except ModuleNotFoundError as e:
        print(f"libvirt package is not installed. [{e}]")

# Hyper-V platform
import lisa.sut_orchestrator.hyperv.platform_  # noqa: F401

# Transformers
import lisa.transformers.dom0_kernel_installer  # noqa: F401
import lisa.transformers.dump_variables  # noqa: F401
import lisa.transformers.file_uploader  # noqa: F401
import lisa.transformers.kernel_source_installer  # noqa: F401
import lisa.transformers.package_installer  # noqa: F401
import lisa.transformers.repo_package_installer  # noqa: F401
import lisa.transformers.rpm_kernel_installer  # noqa: F401
import lisa.transformers.script_file_transformer  # noqa: F401
import lisa.transformers.script_transformer  # noqa: F401
import lisa.transformers.to_list  # noqa: F401
import lisa.transformers.upgrade_packages  # noqa: F401
