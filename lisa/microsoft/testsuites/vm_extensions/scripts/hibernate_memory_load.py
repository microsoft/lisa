# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import random
import sys
import time


def main() -> None:
    target = int(sys.argv[1])
    ready_path = sys.argv[2]
    chunk = 1024 * 1024
    randbytes = getattr(random, "randbytes", os.urandom)

    buffers = []
    allocated = 0
    while allocated < target:
        size = min(chunk, target - allocated)
        buffers.append(bytearray(randbytes(size)))
        allocated += size

    with open(ready_path, "w") as ready:
        ready.write(str(allocated))

    page = 4096
    while True:
        for buffer in buffers:
            for offset in range(0, len(buffer), page):
                buffer[offset] = (buffer[offset] + 1) % 256
        time.sleep(20)


if __name__ == "__main__":
    main()
