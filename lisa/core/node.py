class Node:
    def __init__(self, isRemote=True, isDefault=False):
        self.isDefault: bool = isDefault
        self.isRemote: bool = isRemote
        self.sshSession = None

    def connect(self):
        if self.sshSession is None:
            pass
