import logging
import os
import time

# to prevent circular import, hard code it here.
env_result_path = "LISA_RESULT_PATH"


def init_log():
    format = "%(asctime)s.%(msecs)03d[%(levelname)-.1s]%(name)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=format,
        datefmt="%m%d %H:%M:%S",
        handlers=[
            logging.FileHandler("%s/lisa-host.log" % os.getenv(env_result_path)),
            logging.StreamHandler(),
        ],
    )
    logging.Formatter.converter = time.gmtime


log = logging.getLogger("LISA")
