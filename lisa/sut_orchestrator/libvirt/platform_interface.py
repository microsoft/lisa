from abc import ABC, abstractmethod

from lisa.node import Node


class IBaseLibvirtPlatform(ABC):
    @abstractmethod
    def restart_domain_and_attach_logger(self, node: Node) -> None:
        pass
