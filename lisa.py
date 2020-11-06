from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from _pytest.mark.structures import Mark

# Setup a sane configuration for local and remote commands. Note that
# the defaults between Fabric and Invoke are different, so we use
# their Config classes explicitly.
config = {
    "run": {
        # Show each command as its run.
        "echo": True,
        # Disable stdin forwarding.
        "in_stream": False,
        # Don’t let remote commands take longer than five minutes
        # (unless later overridden). This is to prevent hangs.
        "command_timeout": 1200,
    }
}


def validate(mark: Mark):
    """Validate each test's LISA parameters."""
    assert not mark.args, "LISA marker cannot have positional arguments!"
    args = mark.kwargs

    if args.get("platform"):
        assert type(args["platform"]) is str, "Platform must be a string!"

    if args.get("priority") is not None:
        assert type(args["priority"]) is int, "Priority must be an integer!"

    if args.get("features") is not None:
        if type(args["features"]) is str:
            # Convert single ‘str’ argument to ‘Set[str]’
            features = set()
            features.add(args["features"])
            args["features"] = features
        elif type(args["features"]) is list:
            # Convert ‘list’ to ‘set’
            args["features"] = set(args["features"])
        assert type(args["features"]) is set, "Features must be a set!"
        for feature in args["features"]:
            assert type(feature) is str, "Features must be strings!"
    else:
        args["features"] = set()
