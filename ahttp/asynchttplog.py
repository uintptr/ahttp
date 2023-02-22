import os
import sys
import logging
import threading
import traceback
from typing import Optional


class AsyncLogger:
    def __init__(self, log_file: Optional[str], verbose: bool = False) -> None:

        if (log_file is not None):
            script_root = os.path.abspath(os.path.dirname(sys.argv[0]))
            self.log_file = os.path.join(script_root, "tv.log")

            logging.basicConfig(filename=self.log_file,
                                filemode='a',
                                format='%(asctime)s %(message)s',
                                datefmt='%H:%M:%S',
                                level=logging.DEBUG)

            self.logger = logging.getLogger("tv")
            self.logger_lock = threading.Lock()

            if (True == verbose):
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
