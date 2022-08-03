# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    Optional,
    Type,
    TypeVar,
    Union,
    cast,
)

from lisa import schema
from lisa.util import (
    InitializableMixin,
    LisaException,
    NotMeetRequirementException,
    constants,
)
from lisa.util.logger import get_logger

if TYPE_CHECKING:
    from lisa.node import Node
    from lisa.platform_ import Platform


class Feature(InitializableMixin):
    def __init__(
        self, settings: schema.FeatureSettings, node: "Node", platform: "Platform"
    ) -> None:
        super().__init__()
        self._settings = settings
        self._node: Node = node
        self._platform: Platform = platform
        self._log = get_logger("feature", self.name(), self._node.log)

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.FeatureSettings

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    def can_disable(cls) -> bool:
        raise NotImplementedError()

    def enabled(self) -> bool:
        raise NotImplementedError()

    @classmethod
    def get_feature_settings(
        cls, feature: Union[Type["Feature"], schema.FeatureSettings, str]
    ) -> schema.FeatureSettings:
        if isinstance(feature, Feature):
            return feature._settings
        if isinstance(feature, type):
            return schema.FeatureSettings.create(feature.name())
        elif isinstance(feature, str):
            return schema.FeatureSettings.create(feature)
        elif isinstance(feature, schema.FeatureSettings):
            return feature
        else:
            raise LisaException(f"unsupported feature setting type: {type(feature)}")

    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        """
        If a feature need to change something before deployment, it needs to
        implement this method. When this method is called, determined by the
        platform.
        """
        ...

    @classmethod
    def check_supported(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        """
        It's called in platform to check if a node support the feature or not.
        """
        return None

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        override for initializing
        """
        ...


T_FEATURE = TypeVar("T_FEATURE", bound=Feature)


class Features:
    def __init__(self, node: "Node", platform: "Platform") -> None:
        self._node = node
        self._platform = platform
        self._feature_cache: Dict[str, Feature] = {}
        self._feature_types: Dict[str, Type[Feature]] = {}
        self._feature_settings: Dict[str, schema.FeatureSettings] = {}
        for feature_type in platform.supported_features():
            self._feature_types[feature_type.name()] = feature_type
        if node.capability.features:
            for feature_settings in node.capability.features:
                self._feature_settings[feature_settings.type] = feature_settings
        if node.capability.disk:
            self._feature_settings[constants.FEATURE_DISK] = node.capability.disk

    def is_supported(self, feature_type: Type[T_FEATURE]) -> bool:
        return feature_type.name() in self._feature_types

    def __getitem__(self, feature_type: Type[T_FEATURE]) -> T_FEATURE:
        feature_name = feature_type.name()
        feature: Optional[Feature] = self._feature_cache.get(feature_name, None)
        if feature is None:
            registered_feature_type = self._feature_types.get(feature_name)
            if not registered_feature_type:
                raise LisaException(
                    f"feature [{feature_name}] isn't supported on "
                    f"platform [{self._platform.type_name()}]"
                )
            settings = self._feature_settings.get(feature_name, None)
            if not settings:
                # feature is not specified, but should exists
                settings = schema.FeatureSettings.create(feature_name)

            settings_type = registered_feature_type.settings_type()
            settings = schema.load_by_type(settings_type, settings)
            feature = registered_feature_type(
                settings=settings, node=self._node, platform=self._platform
            )
            feature.initialize()
            self._feature_cache[feature_type.name()] = feature

        assert feature
        return cast(T_FEATURE, feature)


def get_feature_settings_type_by_name(
    feature_name: str, features: Iterable[Type[Feature]]
) -> Type[schema.FeatureSettings]:
    for feature in features:
        if feature.name() == feature_name:
            return feature.settings_type()

    raise NotMeetRequirementException(
        f"cannot find feature settings "
        f"for '{feature_name}' in {[x.name() for x in features]}"
    )


def get_feature_settings_by_name(
    feature_name: str, feature_settings: Iterable[schema.FeatureSettings]
) -> schema.FeatureSettings:
    assert feature_settings, "not found features to query"
    for single_setting in feature_settings:
        if single_setting.type == feature_name:
            return single_setting

    raise NotMeetRequirementException(
        f"cannot find feature with type '{feature_name}' in {feature_settings}"
    )
