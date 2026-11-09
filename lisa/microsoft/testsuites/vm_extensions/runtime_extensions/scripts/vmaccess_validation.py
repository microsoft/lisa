# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# Executed as root inside the Linux guest by Custom Script.
import base64
import ctypes
import ctypes.util
import hmac
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

_STATE_FILES = (
    "/etc/ssh/sshd_config",
    "/etc/ssh/sshd_config.d/50-cloud-init.conf",
    "/etc/sudoers.d/waagent",
    "/var/cache/vmaccess/backup",
    "/var/lib/waagent/ovf-env.xml",
)


def _snapshot_state() -> Dict[str, Any]:
    import grp
    import pwd

    users = [entry.pw_name for entry in pwd.getpwall()]
    _require(
        not any(user.startswith(("vmaccess-", "vmaccessuser")) for user in users),
        "A VMAccess test account already exists; refusing to overwrite its state",
    )
    subprocess.run(["/usr/sbin/sshd", "-t"], check=True, capture_output=True, text=True)
    directory = Path(tempfile.mkdtemp(prefix="lisa-vmaccess-state-", dir="/var/tmp"))
    files = []
    for index, filename in enumerate(_STATE_FILES):
        source = Path(filename)
        if source.exists():
            info = source.stat()
            shutil.copy2(source, directory / str(index))
            files.append({"exists": True, "uid": info.st_uid, "gid": info.st_gid})
        else:
            files.append({"exists": False})
    firewall = shutil.which("iptables-save") is not None
    if firewall:
        with (directory / "firewall").open("w") as output:
            subprocess.run(
                ["iptables-save"],
                stdout=output,
                stderr=subprocess.PIPE,
                check=True,
                text=True,
            )
    (directory / "state.json").write_text(
        json.dumps(
            {
                "files": files,
                "users": users,
                "groups": [group.gr_name for group in grp.getgrall()],
                "firewall": firewall,
            }
        )
    )
    return {"snapshot": str(directory)}


def _restore_state(request: Dict[str, Any]) -> Dict[str, Any]:
    import grp
    import pwd

    directory = Path(request["snapshot"])
    _require(
        directory.parent == Path("/var/tmp")
        and directory.name.startswith("lisa-vmaccess-state-")
        and not directory.is_symlink(),
        "Invalid VMAccess state directory",
    )
    state = json.loads((directory / "state.json").read_text())
    if state["firewall"]:
        with (directory / "firewall").open() as source:
            subprocess.run(
                ["iptables-restore"],
                stdin=source,
                capture_output=True,
                check=True,
                text=True,
            )
    for account in pwd.getpwall():
        if account.pw_name not in state["users"] and account.pw_name.startswith(
            ("vmaccess-", "vmaccessuser")
        ):
            subprocess.run(
                ["userdel", "-r", account.pw_name],
                check=True,
                capture_output=True,
                text=True,
            )
    for group in grp.getgrall():
        if group.gr_name not in state["groups"] and group.gr_name.startswith(
            ("vmaccess-", "vmaccessuser")
        ):
            subprocess.run(
                ["groupdel", group.gr_name],
                check=True,
                capture_output=True,
                text=True,
            )
    for index, filename in enumerate(_STATE_FILES):
        destination = Path(filename)
        saved = state["files"][index]
        if saved["exists"]:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(directory / str(index), destination)
            os.chown(destination, saved["uid"], saved["gid"])
        elif destination.exists():
            destination.unlink()
    subprocess.run(["/usr/sbin/sshd", "-t"], check=True, capture_output=True, text=True)
    # Restore the service's effective configuration, not just its files.
    service = subprocess.run(
        ["systemctl", "list-unit-files", "ssh.service", "--no-legend"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["systemctl", "restart", "ssh" if "ssh.service" in service.stdout else "sshd"],
        check=True,
        capture_output=True,
        text=True,
    )
    shutil.rmtree(directory)
    return {}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _password_matches(password: str, stored_hash: str) -> bool:
    _require(
        bool(stored_hash) and not stored_hash.startswith(("!", "*")),
        "Expected an unlocked password hash",
    )
    library = ctypes.util.find_library("crypt")
    _require(library is not None, "libcrypt is required to validate password hashes")
    crypt = ctypes.CDLL(library).crypt
    crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    crypt.restype = ctypes.c_char_p
    actual = crypt(password.encode(), stored_hash.encode())
    _require(actual is not None, "libcrypt could not verify the configured password")
    return hmac.compare_digest(actual, stored_hash.encode())


def _key_fields(key: str) -> List[str]:
    fields = key.split()
    _require(len(fields) >= 2, "Invalid public key")
    return fields[:2]


def _validate_account(request: Dict[str, Any]) -> Dict[str, Any]:
    import pwd

    username = request["username"]
    account = pwd.getpwnam(username)
    home = Path(account.pw_dir)
    if any(
        field in request for field in ("password", "rejected_password", "expiration")
    ):
        with Path("/etc/shadow").open() as shadow_file:
            shadow = next(
                (
                    line.rstrip("\n").split(":")
                    for line in shadow_file
                    if line.split(":", 1)[0] == username
                ),
                None,
            )
        if shadow is None:
            raise RuntimeError("Account has no shadow entry")
        if "password" in request:
            _require(
                _password_matches(request["password"], shadow[1]),
                "Configured password does not match the account hash",
            )
        if "rejected_password" in request:
            _require(
                not _password_matches(request["rejected_password"], shadow[1]),
                "Previous or incorrect password still matches the account hash",
            )
        if "expiration" in request:
            expiration = int(shadow[7]) if shadow[7] else -1
            _require(
                expiration == request["expiration"],
                f"Incorrect account expiration: expected {request['expiration']} "
                f"days since epoch, got {expiration} (-1 means no expiration)",
            )

    if "keys" in request or "absent_keys" in request:
        directory = home / ".ssh"
        authorized_keys = directory / "authorized_keys"
        for path in (directory, authorized_keys):
            info = path.stat()
            _require(info.st_uid == account.pw_uid, "Incorrect key owner")
            _require(
                stat.S_IMODE(info.st_mode) & 0o022 == 0,
                "Key directory/file must not be group/world writable",
            )
        subprocess.run(
            ["ssh-keygen", "-l", "-f", str(authorized_keys)],
            check=True,
            capture_output=True,
            text=True,
        )
        actual_keys = [
            _key_fields(line)
            for line in authorized_keys.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        for key in request.get("keys", []):
            _require(_key_fields(key) in actual_keys, "Expected public key is missing")
        for key in request.get("absent_keys", []):
            _require(
                _key_fields(key) not in actual_keys, "Previous key was not removed"
            )
        if request.get("only_keys"):
            _require(
                actual_keys == [_key_fields(key) for key in request["keys"]],
                "Unexpected or duplicate authorized keys",
            )

    if "passwordless" in request:
        listing = subprocess.run(
            ["sudo", "-l", "-U", username],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        _require("ALL" in listing, "Expected administrator sudo permissions")
        result = subprocess.run(
            ["su", "-", username, "-c", "sudo -k; sudo -n true"],
            capture_output=True,
            text=True,
        )
        if request["passwordless"]:
            _require("NOPASSWD" in listing, "Missing passwordless sudo permission")
            _require(result.returncode == 0, "Passwordless sudo failed")
        else:
            _require(
                result.returncode == 1 and "password" in result.stderr.lower(),
                "Sudo must require a password",
            )
    return {}


def _generate_key(request: Dict[str, Any]) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="lisa-vmaccess-key-") as directory:
        private_key = str(Path(directory) / "key")
        format_ = request.get("format", "openssh")
        if format_ == "certificate":
            certificate = str(Path(directory) / "certificate.pem")
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-nodes",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    private_key,
                    "-out",
                    certificate,
                    "-subj",
                    "/CN=vmaccess-validation",
                    "-days",
                    "1",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            public_key = subprocess.run(
                ["ssh-keygen", "-y", "-f", private_key],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            setting = Path(certificate).read_text()
        else:
            _require(format_ in ("openssh", "ssh2"), "Unsupported key format")
            subprocess.run(
                [
                    "ssh-keygen",
                    "-q",
                    "-t",
                    request.get("algorithm", "rsa"),
                    "-f",
                    private_key,
                    "-N",
                    "",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            public_key = Path(private_key + ".pub").read_text().strip()
            setting = public_key
            if format_ == "ssh2":
                setting = subprocess.run(
                    ["ssh-keygen", "-e", "-f", private_key + ".pub"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
        return {"setting": setting, "public_key": public_key}


def _run(request: Dict[str, Any]) -> Dict[str, Any]:
    _require(os.geteuid() == 0, "VMAccess validation must run as root")
    operation = request["operation"]
    if operation == "snapshot_state":
        return _snapshot_state()
    if operation == "restore_state":
        return _restore_state(request)
    if operation == "validate_account":
        return _validate_account(request)
    if operation == "generate_key":
        return _generate_key(request)
    if operation == "command":
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", request["script"]],
            capture_output=True,
            text=True,
        )
        _require(
            result.returncode == request.get("expected_exit_code", 0),
            f"Guest command exited with {result.returncode}: {result.stderr}",
        )
        return {"stdout": result.stdout}
    raise ValueError(f"Unknown VMAccess validation operation: {operation}")


def main() -> None:
    request = json.loads(base64.b64decode(sys.argv[1]).decode())
    result = _run(request)
    print(request["marker"] + json.dumps(result))


if __name__ == "__main__":
    main()
