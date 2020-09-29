from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional, Type, TypeVar, cast

from lisa.util import InitializableMixin, LisaException

if TYPE_CHECKING:
    from lisa.node import Node
    from lisa.platform_ import Platform


class Feature(InitializableMixin):
    def __init__(self, node: Any, platform: Any) -> None:
        super().__init__()
        self._node: Node = node
        self._platform: Platform = platform

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        raise NotImplementedError()

    @classmethod
    @abstractmethod
    def enabled(cls) -> bool:
        raise NotImplementedError()

    @classmethod
    @abstractmethod
    def can_disable(cls) -> bool:
        raise NotImplementedError()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        override for initializating
        """
        pass


T_FEATURE = TypeVar("T_FEATURE", bound=Feature)


class Features:
    def __init__(self, node: Any, platform: Any) -> None:
        self._node: Node = node
        self._platform: Platform = platform
        self._cache: Dict[str, Feature] = dict()
        self._supported_features: Dict[str, Type[Feature]] = dict()
        for feature_type in platform.supported_features():
            self._supported_features[feature_type.name()] = feature_type

    def __getitem__(self, feature_type: Type[T_FEATURE]) -> T_FEATURE:
        feature_name = feature_type.name()
        feature: Optional[Feature] = self._cache.get(feature_name, None)
        if feature is None:
            registered_feature_type = self._supported_features.get(feature_name)
            if not registered_feature_type:
                raise LisaException(
                    f"feature [{feature_name}] isn't supported on "
                    f"platform [{self._platform.type_name()}]"
                )
            feature = registered_feature_type(self._node, self._platform)
            # not sure why mypy error on this call, have to add type: ignore
            feature.initialize()
            self._cache[feature_type.name()] = feature

        assert feature
        return cast(T_FEATURE, feature)
