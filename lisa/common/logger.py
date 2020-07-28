import logging

import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("%s/lisa.log" % os.environ["RESULT_PATH"]),
        logging.StreamHandler(),
    ],
)

log = logging.getLogger("LISA")
