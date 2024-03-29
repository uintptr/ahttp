
import sys
import ssl
import asyncio

import urllib.parse

from http import HTTPStatus

from .asynchttpcommon import AsyncHttpArgs

DEF_IO_SIZE = (8 * 1024)


class AsyncHttpConnection:
    def __init__(self, host: str, port: int, secure: bool) -> None:
        self.host = host
        self.port = port
        self.secure = secure

        ver = sys.version_info
        self.ua = f"Python/{ver.major}.{ver.minor}.{ver.micro}"

    async def __aenter__(self) -> 'AsyncHttpConnection':
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    ############################################################################
    # PUBLIC METHODS
    ############################################################################

    async def connect(self) -> None:

        if (self.secure):
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            io = await asyncio.open_connection(self.host,
                                               self.port,
                                               ssl=context)
        else:
            io = await asyncio.open_connection(self.host, self.port)

        self.reader = io[0]
        self.writer = io[1]

    async def close(self) -> None:
        if (self.writer):
            self.writer.close()
            await self.writer.wait_closed()

    async def send_request(self, method: str, query: str, user_args: AsyncHttpArgs, http_version: str = "1.0", data: bytes = b'') -> None:

        args = AsyncHttpArgs()

        if (self.port != 80 and self.port != 443):
            args.set("Host", f"{self.host}:{self.port}")
        else:
            args.set("Host", self.host)

        args.merge(user_args)

        if (args.get("User-Agent") == ""):
            args.set("User-Agent", self.ua)

        if (len(data) > 0):
            args.set("Content-Length", str(len(data)))

        req = [f"{method} {query} HTTP/{http_version}"]

        req.extend(args.get_all())

        req_str = '\r\n'.join(req)
        req_str += "\r\n\r\n"

        req_bytes = req_str.encode("utf-8")

        if (len(data) > 0):
            req_bytes += data

        self.writer.write(req_bytes)
        await self.writer.drain()

    async def read_header(self) -> str:
        header = b""

        while (True):
            line = await self.reader.readline()
            line_len = len(line)

            if (line_len == 0):
                break

            header += line

            if (line_len == 2):
                break

        return header.decode("utf-8")

    async def read_all(self, size: int) -> bytes:
        data = b''
        offset = 0

        while (offset < size):

            read_len = min((size - offset), DEF_IO_SIZE)

            chunk = await self.reader.read(read_len)
            chunk_len = len(chunk)

            if (chunk_len == 0):
                break

            data += chunk
            offset += chunk_len

        return data


class AsyncHttpResponse:
    def __init__(self, conn: AsyncHttpConnection, header: str) -> None:
        self.status = 0
        self.args = AsyncHttpArgs()
        self.con = conn
        self.status = HTTPStatus.INTERNAL_SERVER_ERROR

        self._parse_header(header)

    def _parse_header(self, header: str) -> None:

        for line in header.split("\r\n"):
            if (line.startswith("HTTP/")):
                self.status = int(line.split(" ")[1])
            elif ('' != line):
                k, v = line.split(":", 1)
                self.args.set(k, v.lstrip())

    def get_header(self, key: str) -> str:
        return self.args.get(key)

    def get_header_int(self, key: str) -> int:
        return self.args.get_int(key)

    async def read(self, size: int) -> bytes:
        return await self.con.reader.read(size)

    async def read_chunked(self) -> bytes:

        data = b''

        while (True):
            chunk_line = await self.con.reader.readline()

            if (b'' == chunk_line or 2 == len(chunk_line)):
                # end of a chunk
                continue

            sep = chunk_line.index(b"\r")
            chunk_line = chunk_line[:sep]

            chunk_len = int(chunk_line, 16)

            if (chunk_len == 0):
                await self.con.reader.readline()  # empty the socket
                break
            elif (chunk_len < 0):
                ValueError(f"invalid chunk size ({chunk_len})")

            data += await self.con.read_all(chunk_len)

        return data

    async def read_all(self) -> bytes:

        if (self.args.get("Transfer-Encoding") == "chunked"):
            return await self.read_chunked()

        content_len = self.args.get_int("Content-Length")

        if (0 == content_len):
            return b''
        if (content_len > 0):
            return await self.con.read_all(content_len)

        raise ValueError("Invalid response")


class AsyncHttpClient:
    def __init__(self, url: str) -> None:
        self._load_url(url)

    def _load_url(self, url):
        self.url = url
        self.q = urllib.parse.urlparse(url)
        self.header = AsyncHttpArgs()

        if (self.q.hostname is None):
            raise ValueError("Invalid URL")

        self.host = self.q.hostname
        self.secure = self.q.scheme == "https"

    async def __str__(self) -> str:
        return self.url

    async def __aenter__(self) -> 'AsyncHttpClient':
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _init_request(self, method: str, query: str, http_version: str = "1.1", data: bytes = b'') -> AsyncHttpResponse:

        await self.conn.send_request(method, query, self.header, http_version, data=data)
        header = await self.conn.read_header()
        resp = AsyncHttpResponse(self.conn, header)

        if (301 == resp.status or 302 == resp.status):
            await self.close()

            new_url = resp.get_header("Location")

            if (new_url is not None and new_url != ""):
                self._load_url(new_url)

            await self.connect()
            await self.conn.send_request(method, self.q.path, self.header, http_version, data=data)
            header = await self.conn.read_header()
            resp = AsyncHttpResponse(self.conn, header)

        return resp

    ############################################################################
    # PUBLIC METHODS
    ############################################################################

    async def close(self) -> None:
        await self.conn.close()

    async def connect(self) -> None:
        if (self.q.port is None):
            if (self.secure):
                self.port = 443
            else:
                self.port = 80
        else:
            self.port = self.q.port

        self.conn = AsyncHttpConnection(self.host, self.port, self.secure)
        await self.conn.connect()

    def add_header(self, key: str, value: str) -> None:
        self.header.set(key, value)

    async def get(self, query: str, http_version: str = "1.1") -> AsyncHttpResponse:

        await self.conn.send_request("GET", query, self.header, http_version)
        header = await self.conn.read_header()
        resp = AsyncHttpResponse(self.conn, header)

        if (301 == resp.status or 302 == resp.status):
            await self.close()

            new_url = resp.get_header("Location")

            if (new_url is not None and new_url != ""):
                self._load_url(new_url)

            await self.connect()
            await self.conn.send_request("GET", self.q.path, self.header, http_version)
            header = await self.conn.read_header()
            resp = AsyncHttpResponse(self.conn, header)

        return resp

    async def post(self, query: str, http_version: str = "1.1", data: bytes = b'') -> AsyncHttpResponse:
        return await self._init_request("POST", query, http_version, data)
