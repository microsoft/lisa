from datetime import datetime
import os
from retry import retry

path_template = "../runtime/results/{0}/{0}-{1}"


@retry(tries=10, delay=0)
def create_result_path():
    global index
    date = datetime.utcnow().strftime("%Y%m%d")
    time = datetime.utcnow().strftime("%H%M%S-%f")[:-3]
    current_path = path_template.format(date, time)
    if os.path.exists(current_path):
        raise FileExistsError(
            "%s exists, and not found an unique path." % current_path
        )
    return current_path


result_path = os.path.realpath(create_result_path())
os.makedirs(result_path)
os.environ["RESULT_PATH"] = result_path
