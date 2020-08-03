from lisa import Platform


class ReadyPlatform(Platform):
    def platformType(cls) -> str:
        return "ready"

    def config(self, key: str, value: object):
        pass
