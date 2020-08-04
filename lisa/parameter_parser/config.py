from lisa import constants


class Config(dict):
    def __init__(self, config):
        self.config = config

    def validate(self):
        # TODO implement config validation
        pass

    def getExtensions(self):
        return self.config.get(constants.EXTENSIONS)

    def getEnvironment(self):
        return self.config.get(constants.ENVIRONMENT)

    def getPlatform(self):
        return self.config.get(constants.PLATFORM)

    def getTests(self):
        return self.config.get(constants.TESTS)
