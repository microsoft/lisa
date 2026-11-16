import hashlib
import posixpath
import re
from urllib.parse import urlparse

from lisa.executable import Tool

_RE_SCHEME = re.compile(r"^\w+:/*(\w+:|www\.)?")
_RE_SLASH = re.compile(r"[?/:&#|~\*\[\]\(\)'\\]+")
_RE_BEGIN = re.compile(r"^[,.]*")
_RE_FINAL = re.compile(r"[,.]*$")
_RE_NOT_ALLOWED = re.compile(r"[^a-zA-Z0-9_.:-]")


def _repo_id_from_url(url: str) -> str:
    """
    Derive the repo id yum-config-manager generates for a repo URL.

    Mirrors sanitize_url_to_fs() in dnf-plugins-core's config_manager.py so
    that set_opt() targets the same repo section --add-repo created.
    """
    if _RE_SCHEME.match(url):
        try:
            url = url.encode("idna").decode("utf-8")
        except UnicodeError:
            pass
    url = _RE_SCHEME.sub("", url)
    url = _RE_SLASH.sub("_", url)
    url = _RE_BEGIN.sub("", url)
    url = _RE_FINAL.sub("", url)
    if len(url) > 250:
        parts = url[:185].split("_")
        last_index = 185 - len(parts[-1])
        digest = hashlib.sha256(url[last_index:].encode("utf-8")).hexdigest()
        url = url[:last_index] + "_" + digest
    return _RE_NOT_ALLOWED.sub("", url)


class YumConfigManager(Tool):
    @property
    def command(self) -> str:
        return "yum-config-manager"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        package_name = "yum-utils"
        self.node.os.install_packages(package_name)  # type: ignore
        return self._check_exists()

    def add_repository(
        self,
        repo: str,
        no_gpgcheck: bool = True,
    ) -> None:
        cmd = f'{self.command} --add-repo "{repo}"'
        if no_gpgcheck:
            cmd += " --nogpgcheck"
        self.node.execute(
            cmd=cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to add repository",
        )
        # dnf 4.19 silently ignores --nogpgcheck for --add-repo, leaving the
        # generated repo file without gpgcheck=0. Persist it explicitly.
        if no_gpgcheck:
            url = repo
            if not urlparse(url).scheme:
                url = "file://" + posixpath.abspath(url)
            if not url.endswith(".repo"):
                self.set_opt(f"{_repo_id_from_url(url)}.gpgcheck=0")

    def set_opt(
        self,
        opts: str,
    ) -> None:
        self.run(
            f"--save --setopt={opts}",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to set opts {opts}",
        )
