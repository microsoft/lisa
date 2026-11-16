# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path("/var/lib/lisa-vmapplications")
OWNER = "lisa-vmapplications"


def read_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"Expected an object in {path}"
    return value


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def check_owner(data: Dict[str, Any]) -> None:
    assert not ROOT.is_symlink(), "Fixture root must not be a symbolic link"
    owner = read_json(ROOT / "owner.json")
    assert owner == {"owner": OWNER, "vm_id": data["vm_id"]}, owner


def append_event(event: Dict[str, Any]) -> None:
    with (ROOT / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def handler_status() -> Any:
    files = [
        path
        for publisher in ("Microsoft.CPlat.Core", "Microsoft.CPlat.Core.Edp")
        for path in Path("/var/lib/waagent").glob(
            f"{publisher}.VMApplicationManagerLinux-*/status/*.status"
        )
    ]
    if not files:
        return None
    latest = max(files, key=lambda path: path.stat().st_mtime_ns)
    statuses = json.loads(latest.read_text(encoding="utf-8"))
    assert isinstance(statuses, list) and statuses
    message = statuses[0]["status"]["formattedMessage"]["message"]
    status = json.loads(message[message.index("{") :])
    return {
        "handler": "VMApplicationManagerLinux",
        "version": latest.parent.parent.name.rsplit("-", 1)[1],
        "actions": [
            {
                "name": item["package"],
                "version": item["version"],
                "op": item["operation"],
                "result": (
                    "SUCCESS"
                    if item["result"] == "SUCCESS"
                    else "SKIPPED"
                    if "skipped" in item["result"].lower()
                    else "FAILED"
                ),
            }
            for item in status.get("ActionsPerformed", [])
        ],
        "error": bool(status.get("Errors") or status.get("CriticalError")),
    }


def utility(operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if operation == "configure":
        if not ROOT.exists():
            ROOT.mkdir(mode=0o700)
            (ROOT / "owner.json").write_text(
                json.dumps({"owner": OWNER, "vm_id": data["vm_id"]}),
                encoding="utf-8",
            )
        check_owner(data)
        if not (ROOT / "unrelated.txt").exists():
            (ROOT / "unrelated.txt").write_bytes(
                b"LISA VMApplications unrelated file\n"
            )
        (ROOT / "state").mkdir(exist_ok=True)
        (ROOT / "control.json").write_text(json.dumps(data), encoding="utf-8")
        return {}
    check_owner(data)
    if operation == "cleanup":
        shutil.rmtree(ROOT)
        return {}
    assert operation == "inspect", operation
    events = []
    path = ROOT / "events.jsonl"
    if path.exists():
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    events = [event for event in events if event["run"] == data["run"]]
    states = {path.stem: read_json(path) for path in (ROOT / "state").glob("*.json")}
    return {
        "run": data["run"],
        "events": [
            {
                key: value
                for key, value in event.items()
                if key not in ("run", "directory")
            }
            for event in events
        ],
        "states": states,
        "boot": boot_id(),
        "status": handler_status(),
        "unrelated": hashlib.sha256((ROOT / "unrelated.txt").read_bytes()).hexdigest(),
        "directories": {
            event["app"]: event["directory"] for event in events if "directory" in event
        },
        "present": {
            event["app"]: Path(event["directory"]).exists()
            for event in events
            if "directory" in event
        },
    }


def application(operation: str, data: Dict[str, Any]) -> None:
    control = read_json(ROOT / "control.json")
    check_owner(control)
    assert os.geteuid() == 0, "Application command must run as root"
    directory = Path.cwd()
    assert directory.name == data["version"], str(directory)
    assert directory.parent.name == data["name"], str(directory)
    alias = data["app"]
    state = ROOT / "state" / f"{alias}.json"
    event: Dict[str, Any] = {
        "run": control["run"],
        "app": alias,
        "op": operation,
        "version": data["version"],
        "directory": str(directory),
        "result": "success",
    }
    if operation in ("install", "update"):
        package = directory / data["package"]
        assert hashlib.sha256(package.read_bytes()).hexdigest() == data["sha256"]
        assert stat.S_IMODE(package.stat().st_mode) & 0o077 == 0
        expected = control.get("configuration", {}).get(alias, data["config_sha256"])
        config = directory / data["config"]
        if expected is None:
            assert not config.exists(), f"Unexpected configuration file: {config}"
        else:
            assert hashlib.sha256(config.read_bytes()).hexdigest() == expected
            assert stat.S_IMODE(config.stat().st_mode) & 0o077 == 0
        for required in control.get("requires", {}).get(alias, []):
            assert (ROOT / "state" / f"{required}.json").exists(), required
    if operation == "action":
        event["action"] = data["action"]
        parameters = {
            name: os.environ.get(name) for name in ("LISA_REQUIRED", "LISA_OPTIONAL")
        }
        assert parameters == control["parameters"], parameters
        event["parameters"] = parameters
    failed = bool(control.get("failures", {}).get(f"{alias}.{operation}"))
    failed = failed or (operation == "action" and data["action"] == "fail")
    if failed:
        event["result"] = "failed"
        append_event(event)
        raise RuntimeError(f"LISA intentional failure: {alias}.{operation}")

    reboot = control.get("reboot", {}).get(alias) == operation
    reboot_marker = ROOT / f"reboot-{alias}-{operation}-{data['version']}"
    if reboot and not reboot_marker.exists():
        reboot_marker.write_text(boot_id(), encoding="utf-8")
        event["result"] = "reboot"
        append_event(event)
        subprocess.run(["shutdown", "-r", "now"], check=True)
        time.sleep(180)
        raise RuntimeError("The requested reboot did not terminate the command")

    if operation in ("install", "update"):
        state.write_text(
            json.dumps({"version": data["version"], "run": control["run"]}),
            encoding="utf-8",
        )
        if alias in control.get("mutate", []):
            package = directory / data["package"]
            content = bytearray(package.read_bytes())
            content[-1] ^= 1
            package.write_bytes(content)
            if data["config_sha256"] is not None:
                config = directory / data["config"]
                config.write_bytes(config.read_bytes() + b"x")
    elif operation == "remove":
        if state.exists():
            state.unlink()
    else:
        assert operation == "action", operation
    append_event(event)


def main() -> None:
    operation = sys.argv[-2]
    data = json.loads(base64.b64decode(sys.argv[-1]).decode("utf-8"))
    assert isinstance(data, dict)
    if operation in ("configure", "inspect", "cleanup"):
        result = utility(operation, data)
        print(data["marker"] + json.dumps(result, ensure_ascii=True))
    else:
        application(operation, data)


if __name__ == "__main__":
    main()
