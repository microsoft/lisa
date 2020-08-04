from lisa import Platform, Environment


class ReadyPlatform(Platform):
    def platformType(cls) -> str:
        return "ready"

    def config(self, key: str, value: object):
        # ready platform has no config
        pass

    def requestEnvironment(self, environment: Environment):
        return environment

    def deleteEnvironment(self, environment: Environment):
        # ready platform doesn't support delete environment
        pass
