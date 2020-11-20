from lisa.executable import Tool


class Cat(Tool):
    @property
    def command(self) -> str:
        return "cat"

    def _check_exists(self) -> bool:
        return True
