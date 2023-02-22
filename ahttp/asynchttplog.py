import os
import sys
import logging
import threading
import traceback
from typing import Optional


class AsyncLogger:
    def __init__(self, log_file: Optional[str], verbose: bool = False) -> None:

        if (log_file is not None or True == verbose):
            logging.basicConfig(filename=log_file,
                                filemode='a',
                                format='%(asctime)s %(message)s',
                                datefmt='%H:%M:%S',
                                level=logging.DEBUG)

            self.logger = logging.getLogger("ahttp")
            self.logger_lock = threading.Lock()

            if (True == verbose and log_file is not None):
                self.logger.addHandler(logging.StreamHandler(sys.stdout))
        else:
            self.logger = None

    def log(self, msg) -> None:

        if (self.logger is None):
            return

        callers = traceback.extract_stack()
        count = len(callers)
        caller = callers[count-2]
        caller_file = os.path.basename(caller.filename)
        caller_file = f"{caller_file}:{caller.lineno}"
        caller_func = f"{caller.name}()"

        with self.logger_lock:
            self.logger.info(f"{caller_file:<25} {caller_func:<20} {msg}")

    def exception(self, e: Exception) -> None:

        if (self.logger is None):
            return

        str = traceback.format_exc()
        with self.logger_lock:
            self.logger.info(str)
