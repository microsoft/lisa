from datetime import datetime
from typing import Any, List, Type, cast

from lisa import messages, notifier, schema
from lisa.util import LisaException, plugin_manager

from .common_database import DatabaseMixin, DatabaseSchema

DEFAULT_NAME = "default"


class LsgProvisionBootTime(DatabaseMixin, notifier.Notifier):
    def __init__(self, runbook: DatabaseSchema) -> None:
        DatabaseMixin.__init__(self, runbook, ["ProvisionBootTime"])
        notifier.Notifier.__init__(self, runbook)

    @classmethod
    def type_name(cls) -> str:
        return "lsg_provision_boot_time"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return DatabaseSchema

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize()
        self._log.info("initializing provision boot time notifier...")
        self.ProvisionBootTime = self.base.classes.ProvisionBootTime
        plugin_manager.register(self)

    def _process_provision_boot_time_message(
        self, message: messages.MessageBase
    ) -> None:
        pbt_message: messages.ProvisionBootTimeMessage = cast(
            messages.ProvisionBootTimeMessage, message
        )
        pbt_time = self.ProvisionBootTime()
        pbt_time.BootTimes = pbt_message.boot_times
        pbt_time.DeploymentTime = pbt_message.provision_time
        pbt_time.KernelBootTime = pbt_message.kernel_boot_time
        pbt_time.InitrdBootTime = pbt_message.initrd_boot_time
        pbt_time.UserSpaceBootTime = pbt_message.userspace_boot_time
        pbt_time.CreatedDate = datetime.utcnow()
        pbt_time.Image = pbt_message.information.pop("image", "")
        pbt_time.KernelVersion = pbt_message.information.pop("kernel_version", "")
        pbt_time.HostVersion = pbt_message.information.pop("host_version", "")
        pbt_time.WALAVersion = pbt_message.information.pop("wala_version", "")
        pbt_time.Location = pbt_message.information.pop("location", "")
        pbt_time.VMSize = pbt_message.information.pop("vmsize", "")
        pbt_time.Platform = pbt_message.information.pop("platform", "")
        pbt_time.VMGeneration = pbt_message.information.pop("vm_generation", 0)
        pbt_time.DistroVersion = pbt_message.information.pop("distro_version", "")
        pbt_time.Architecture = pbt_message.information.pop("hardware_platform", "")
        pbt_time.TestProjectName = self._test_project_name
        pbt_time.TestPassName = self._test_pass_name

        session = self.create_session()
        session.add(pbt_time)
        self.commit_and_close_session(session)

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, messages.TestRunMessage):
            if message.status == messages.TestRunStatus.INITIALIZING:
                self._test_project_name = (
                    message.test_project if message.test_project else DEFAULT_NAME
                )
                self._test_pass_name = (
                    message.test_pass if message.test_pass else DEFAULT_NAME
                )
        elif isinstance(message, messages.ProvisionBootTimeMessage):
            self._process_provision_boot_time_message(message)
        else:
            raise LisaException(f"unsupported message type: {type(message)}")

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [messages.ProvisionBootTimeMessage, messages.TestRunMessage]
