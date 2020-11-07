import yaml

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader  # type: ignore

from schema import And, Optional, Schema, Use

criteria_schema = Schema(
    {
        # TODO: Validate that these strings are valid regular
        # expressions if we change our matching logic.
        Optional("name", default=None): str,
        Optional("area", default=None): str,
        Optional("category", default=None): str,
        Optional("priority", default=None): int,
        Optional("tags", default=list): [str],
        Optional("times", default=1): int,
        Optional("exclude", default=False): bool,
    }
)

# NOTE: We could have each platform register its own schema and
# “Or(...)” them together, so this is actually quite flexible. Again,
# so far just writing a proof-of-concept because we need to peer
# review our design.
target_schema = Schema(
    {
        # TODO: Maybe set name to image if unset.
        "name": str,
        # TODO: Use ‘Or([list of registered platforms])’
        "platform": str,
        # TODO: Maybe validate as URN or path etc.
        Optional("image", default=None): str,
        Optional("sku", default=None): str,
    }
)

default_target = {"name": "Default", "platform": "Local"}

schema = Schema(
    And(
        # NOTE: This is “magic” that automatically loads and validates
        # YAML input. See https://pypi.org/project/schema/ and
        # https://pyyaml.org/wiki/PyYAMLDocumentation for
        # documentation.
        Use(lambda x: yaml.load(x, Loader=Loader)),
        {
            Optional("targets", default=[default_target]): [target_schema],
            Optional("criteria", default=list): [criteria_schema],
        },
    )
)
