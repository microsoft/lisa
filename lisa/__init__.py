from datetime import datetime
import random
import os

result_path = "../runtime/results/{}-{}".format(
    datetime.now().strftime("%Y%m%d-%H%M%S"), random.randint(0, 1000)
)

os.makedirs(result_path)
os.environ["RESULT_PATH"] = result_path
