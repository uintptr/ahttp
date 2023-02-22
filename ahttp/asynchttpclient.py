
import asyncio
import sys
from typing import Union, Tuple, AsyncGenerator
from asyncio import StreamReader, StreamWriter
import ssl
import io
from http.client import HTTPResponse
import socket
from urllib.parse import urlparse
from http import HTTPStatus

from .asynchttpcommon import AsyncHttpArgs, AsyncHttpException

DEF_READ_CHUNK_SIZE = 1024


class FakeSocket():
    def __init__(self, response_bytes) -> None:
        self._file = io.BytesIO(response_bytes)

    def makefile(self, *args, **kwargs) -> io.BytesIO:
        return self._file


class AsyncHttpConnection():
    def __init__(self, url: str) -> None:
        self.reader: StreamReader
        self.writer: Union[StreamWriter, None] = None
        self.q = urlparse(url)
        self.args = AsyncHttpArgs()
        self.response_bytes = b''

        ver = sys.version_info
        self.ua = f"Python/{ver.major}.{ver.minor}.{ver.micro}"

        if (None == self.q.port):
            if ("https" == self.q.scheme):
                self.port = 443
            else:
                self.port = 80
        else:
            self.port = self.q.port

        if (self.q.path == ""):
            self.path = "/"
        else:
            self.path = self.q.path

    async def _read_http_header(self) -> bytes:

        header = b""

        while (True):
            line = await self.reader.readline()
            line_len = len(line)

            if (line_len == 0):
                break

            header += line

            if (line_len == 2):
                break

        return header

    async def connect(self) -> None:

        if ("https" == self.q.scheme):
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            io = await asyncio.open_connection(self.q.hostname,
                                               self.port,
                                               ssl=context)
        else:
            io = await asyncio.open_connection(self.q.hostname,
                                               self.port)

        self.reader = io[0]
        self.writer = io[1]

        args = AsyncHttpArgs()

        if (self.q.hostname is not None):
            if (self.port != 80 and self.port != 443):
                args.set("Host", f"{self.q.hostname}:{self.port}")
            else:
                args.set("Host", self.q.hostname)

        args.set("User-Agent", self.ua)

        if (self.q.query is not None and '' != self.q.query):
            req = [f"GET {self.path}?{self.q.query} HTTP/1.0"]
        else:
            req = [f"GET {self.path} HTTP/1.0"]

        req.extend(args.get_all())

        req_str = '\r\n'.join(req)
        req_str += "\r\n\r\n"

        self.writer.write(req_str.encode("utf-8"))
        await self.writer.drain()

        self.response_bytes = await self._read_http_header()

        if (self.response_bytes == b''):
            raise AsyncHttpException("Empty response")

        src = FakeSocket(self.response_bytes)
        self.res = HTTPResponse(src)  # type: ignore
        self.res.begin()

    async def close(self) -> None:
        if (self.writer is not None):
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None


class AsyncHttpClient():
    def __init__(self, url: str) -> None:
        self.url = url
        self.conn = None

    async def __aenter__(self):

        success = False
        # 3 for:
        # 1. http -> https
        # 2. www -> bleh
        max_attempts = 3
        retry = True
        url = self.url

        while (False == success and max_attempts > 0 and True == retry):

            retry = False

            conn = AsyncHttpConnection(url)
            try:
                await conn.connect()
                if (conn.res.status >= 200 and conn.res.status < 300):
                    success = True
                if (HTTPStatus.FOUND == conn.res.status or
                        HTTPStatus.MOVED_PERMANENTLY == conn.res.status):
                    new_url = conn.res.getheader("Location")
                    if (new_url is not None):
                        url = new_url
                        retry = True
                    else:
                        raise AsyncHttpException("Invalid redirect")
            except socket.gaierror as e:
                raise AsyncHttpException(f"Unable to connect {e}")
            finally:
                max_attempts -= 1
                if (False == success):
                    await conn.close()
                else:
                    self.conn = conn

        if (self.conn is None):
            raise AsyncHttpException(f"Connection Failure to {url}")

        return self

    async def __aexit__(self, type, value, traceback) -> None:
        if (self.conn is not None):
            await self.conn.close()
            self.conn = None

    async def close(self) -> None:
        if (self.conn is not None):
            await self.conn.close()
            self.conn = None

    ############################################################################
    # PUBLIC
    ############################################################################

    async def stream(self, bytes_count: int = DEF_READ_CHUNK_SIZE) -> AsyncGenerator[bytes, None]:
        if (self.conn is None):
            raise AsyncHttpException("Not connected")

        while (True):
            data = await self.conn.reader.read(bytes_count)

            if (len(data) == 0 or data == b''):
                break

            yield data

    def get_response_raw(self) -> bytes:
        if (self.conn is None):
            raise AsyncHttpException("Not connected")
        return self.conn.response_bytes

    def get_rw(self) -> Tuple[StreamReader, StreamWriter]:
        if (self.conn is None or self.conn.writer is None):
            raise AsyncHttpException("Not connected")
        return (self.conn.reader, self.conn.writer)

    async def read(self, bytes_count: int = DEF_READ_CHUNK_SIZE) -> bytes:
        if (self.conn is None):
            raise AsyncHttpException("Not connected")
        return await self.conn.reader.read(bytes_count)

    def get_header_int(self, key: str) -> Union[int, None]:
        if (self.conn is None):
            raise AsyncHttpException("Not connected")
        if (key in self.conn.res.headers):
            return int(self.conn.res.headers[key])
        return None
