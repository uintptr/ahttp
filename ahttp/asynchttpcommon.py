from typing import Dict
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from http import HTTPStatus
from typing import List
from urllib.parse import urlparse


class AsyncHttpException(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        self.code: int

    def __str__(self):
        return f"{self.code} ({self.message})"


class AsyncHttpNotImplemented(AsyncHttpException):
    code = HTTPStatus.NOT_IMPLEMENTED


class AsyncHttpNotFound(AsyncHttpException):
    code = HTTPStatus.NOT_FOUND


class AsyncHttpBadRequest(AsyncHttpException):
    code = HTTPStatus.BAD_REQUEST


class AsyncHttpLengthRequired(AsyncHttpException):
    code = HTTPStatus.LENGTH_REQUIRED


class HttpRequest(BaseHTTPRequestHandler):
    def __init__(self, data: bytes) -> None:
        self.rfile = BytesIO(data)
        self.raw_requestline = self.rfile.readline()
        self.error_code = self.error_message = None
        self.valid = self.parse_request()

    def __str__(self) -> str:
        return f"{self.requestline}"

    def send_error(self, code, message) -> None:
        pass


class AsyncHttpArgs():
    def __init__(self) -> None:
        self.args: Dict[str, str] = {}

    def _valid_url(self, url: str) -> bool:
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False

    def merge(self, args: 'AsyncHttpArgs') -> None:
        for k in args.args:
            self.args[k] = args.get(k)

    def set(self, k: str, v: str) -> None:
        self.args[k.lower()] = v

    def get_url(self, k: str, default="", mandatory: bool = False) -> str:
        # validate that the url is valid
        if (k in self.args):
            url = self.args[k]
            if (True == self._valid_url(url)):
                return self.args[k]
            else:
                raise AsyncHttpBadRequest(f'Invalid url: "{url}"')

        if (mandatory):
            raise AsyncHttpBadRequest(f"Missing argument: {k}")

        return default

    def get(self, k: str, default: str = "", mandatory: bool = False) -> str:

        k = k.lower()

        if (k in self.args):
            return self.args[k]

        if (mandatory):
            raise AsyncHttpBadRequest(f"Missing argument: {k}")

        return default

    def get_int(self, k: str, default: int = -1, mandatory: bool = False) -> int:
        k = k.lower()
        if (k in self.args):
            return int(self.args[k])

        if (mandatory):
            raise AsyncHttpBadRequest(f"Missing argument: {k}")

        return default

    def get_float(self, k: str, default: float = 0, mandatory: bool = False) -> float:
        k = k.lower()
        if (k in self.args):
            return float(self.args[k])

        if (mandatory):
            raise AsyncHttpBadRequest(f"Missing argument: {k}")

        return default

    def get_all(self) -> List[str]:
        args = []

        for k in self.args:
            args.append(f"{k}: {self.args[k]}")

        return args
