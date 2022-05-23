# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# The file imports all the mix-in types that can be initialized
# using reflection.

import platform

import lisa.combinators.batch_combinator  # noqa: F401
import lisa.combinators.csv_combinator  # noqa: F401
import lisa.combinators.grid_combinator  # noqa: F401
import lisa.notifiers.console  # noqa: F401
import lisa.notifiers.env_stats  # noqa: F401
import lisa.notifiers.file  # noqa: F401
import lisa.notifiers.html  # noqa: F401
import lisa.notifiers.junit  # noqa: F401
import lisa.notifiers.text_result  # noqa: F401
import lisa.runners.lisa_runner  # noqa: F401
import lisa.sut_orchestrator.ready  # noqa: F401

try:
    import lisa.runners.legacy_runner  # noqa: F401
except ModuleNotFoundError:
    print("win32 package is not installed, legacy runner is not supported.")

# Azure modules
try:
    import lisa.sut_orchestrator.azure.hooks  # noqa: F401
    import lisa.sut_orchestrator.azure.transformers  # noqa: F401
except ModuleNotFoundError:
    print("azure package is not installed.")


if platform.system() == "Linux":
    # libvirt modules
    try:
        import lisa.sut_orchestrator.libvirt.ch_platform  # noqa: F401
        import lisa.sut_orchestrator.libvirt.context  # noqa: F401
        import lisa.sut_orchestrator.libvirt.platform  # noqa: F401
        import lisa.sut_orchestrator.libvirt.qemu_platform  # noqa: F401
        import lisa.sut_orchestrator.libvirt.schema  # noqa: F401
        import lisa.sut_orchestrator.libvirt.transformers  # noqa: F401
    except ModuleNotFoundError:
        print("libvirt package is not installed")

import lisa.transformers.dump_variables  # noqa: F401
import lisa.transformers.kernel_source_installer  # noqa: F401
import lisa.transformers.script_transformer  # noqa: F401
import lisa.transformers.to_list  # noqa: F401
