from lisa.core.environment import Environment


class Platform:
    platformType: str = ""

    def config(self, key: str, value: object):
        pass

    def requestEnvironment(self, environmentSpec):
        pass

    def deleteEnvironment(self, environment: Environment):
        pass
