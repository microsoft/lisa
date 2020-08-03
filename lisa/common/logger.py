import logging
import time
from lisa.common import env


def init_log():
    format = "%(asctime)s.%(msecs)03d[%(levelname)-.1s]%(name)s %(message)s"
    logging.basicConfig(
        level=logging.DEBUG,
        format=format,
        datefmt="%m%d %H:%M:%S",
        handlers=[
            logging.FileHandler(
                "%s/lisa-host.log" % env.get_env(env.RESULT_PATH)
            ),
            logging.StreamHandler(),
        ],
    )
    logging.Formatter.converter = time.gmtime


log = logging.getLogger("LISA")
