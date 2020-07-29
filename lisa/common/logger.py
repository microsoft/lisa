import logging
import time
import os


def init_log():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%m%d %H:%M:%S",
        handlers=[
            logging.FileHandler(
                "%s/lisa-host.log" % os.environ["RESULT_PATH"]
            ),
            logging.StreamHandler(),
        ],
    )
    logging.Formatter.converter = time.gmtime


log = logging.getLogger("LISA")
