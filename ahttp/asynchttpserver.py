#!/usr/bin/env python3
import os
import sys
import asyncio
from asyncio import StreamReader, StreamWriter
from typing import List, Union, Callable, Awaitable, Optional, Tuple, Dict
import urllib.parse
import json
import io
import mimetypes
import http.client
import inspect
from datetime import datetime
from dataclasses import dataclass
import re
import time

from .asynchttpcommon import HttpRequest, AsyncHttpArgs
from .asynchttpcommon import AsyncHttpNotImplemented
from .asynchttpcommon import AsyncHttpBadRequest, AsyncHttpNotFound
from .asynchttpcommon import AsyncHttpLengthRequired, AsyncHttpException
from .asynchttplog import AsyncLogger


@dataclass
class AsyncHttpCacheEntry:
    url: str
    data: bytes
    creation_time: float


IO_SIZE = (1024 * 8)


# just a type to help us validater user inputs
class AsyncHttpURL:
    def __init__(self, url: str) -> None:
        self.url = url

    def __str__(self) -> str:
        return self.url


class AsyncHttpRequest():
    def __init__(self, reader: StreamReader, writer: StreamWriter) -> None:
        self.code = 200
        self.headers: List[str] = []
        self.args: AsyncHttpArgs = AsyncHttpArgs()
        self.request: HttpRequest
        ver = sys.version_info
        self.server = f"Python/{ver.major}.{ver.minor}.{ver.micro}"
        self.reader = reader
        self.writer = writer
        self.headers_sent = False
        self.mime_type: Union[str, None] = None
        self.keep_alive = False
        self.error_message: Union[str, None] = None

    def _init_request(self, request: HttpRequest) -> None:
        self.code = 200
        self.headers = []
        self.args = AsyncHttpArgs()
        self.request = request
        self.headers_sent = False

        if ("Host" in request.headers):
            self.host = request.headers["Host"]
        else:
            self.host = "localhost"

        q = urllib.parse.urlparse(request.path)
        args = urllib.parse.parse_qs(q.query)

        self.path = urllib.parse.unquote(q.path)

        if (args is not None):
            for a in args:
                self.args.set(a, args[a][0])

        if ("Keep-Alive" in request.headers):
            self.keep_alive = True

    def _set_server(self, server: str) -> None:
        self.server = server

    def _http_ts(self, dt) -> str:
        """Return a string representation of a date according to RFC 1123
        (HTTP/1.1).

        The supplied date must be in UTC.

        """
        weekday = ["Mon", "Tue", "Wed", "Thu",
                   "Fri", "Sat", "Sun"][dt.weekday()]
        month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
                 "Oct", "Nov", "Dec"][dt.month - 1]
        return "%s, %02d %s %04d %02d:%02d:%02d GMT" % (weekday, dt.day, month,
                                                        dt.year, dt.hour, dt.minute, dt.second)

    ############################################################################
    # PUBLIC
    ############################################################################

    def get_writer(self) -> StreamWriter:
        return self.writer

    def set_writer(self, writer: StreamWriter) -> None:
        self.writer = writer

    def get_rw(self) -> Tuple[StreamReader, StreamWriter]:
        return self.reader, self.writer

    def set_mime_type(self, mime_type: str) -> None:
        self.mime_type = mime_type

    def set_status(self, code) -> None:
        self.code = code

    def send_response(self, code: int) -> None:
        self.code = code

    def add_header(self, name: str, value: str) -> None:
        self.headers.append(f"{name}: {value}")

    def add_content_length(self, len: int) -> None:
        self.add_header("Content-Length", str(len))

    async def send_as_json(self, data) -> None:

        json_bytes = json.dumps(data, indent=4).encode("utf-8")
        self.add_header("Content-Length", str(len(json_bytes)))
        self.add_header("Content-Type", "application/json")
        await self.send_headers()
        self.writer.write(json_bytes)
        await self.writer.drain()

    async def read_as_json(self) -> Dict:

        if ("Content-Length" not in self.request.headers):
            raise AsyncHttpLengthRequired("Content-Length not set")

        content_len = int(self.request.headers["Content-Length"])

        data = await self.reader.read(content_len)
        return json.loads(data.decode("utf-8"))

    async def read_json_as_args(self) -> AsyncHttpArgs:

        args = AsyncHttpArgs()
        data = await self.read_as_json()

        for k in data:
            args.set(k, data[k])

        return args

    async def send_as_text(self, string: str, mime_type: Optional[str] = None) -> None:

        data_bytes = string.encode("utf-8")

        if (mime_type is not None):
            self.set_mime_type(mime_type)
        self.add_content_length(len(data_bytes))
        await self.send_headers()

        self.writer.write(data_bytes)
        await self.writer.drain()

    async def send_error(self, message: str) -> None:
        e = {}
        e["message"] = message
        await self.send_as_json(e)

    async def send_file(self, file_path: str) -> None:

        if (False == os.path.isfile(file_path)):
            self.set_status(404)
            return await self.send_headers()

        if (self.mime_type is not None):
            self.add_header("Content-Type", self.mime_type)
        else:
            mime_type = mimetypes.guess_type(file_path)[0]
            if (mime_type is not None):
                self.add_header("Content-Type", mime_type)

        file_stat = os.stat(file_path)
        file_size = file_stat.st_size

        start_offset = 0
        end_offset = file_size

        if ("Range" in self.request.headers):
            range = self.request.headers["Range"]
            if (range.startswith("bytes=")):
                range = range[6:]
                ranges = range.split("-")

                if (len(ranges) >= 1):
                    start_offset = int(ranges[0])

                if (2 == len(ranges) and ranges[1] != ''):
                    end_offset = int(ranges[1])
            self.set_status(206)
            content_len = end_offset - start_offset + 1
        else:
            self.set_status(200)
            content_len = file_size

        self.add_header("Connection", "keep-alive")
        self.add_header("Cache-Control", "no-cache")
        self.add_header("Content-Length", str(content_len))
        last_mod_dt = datetime.fromtimestamp(file_stat.st_mtime)
        self.add_header("Last-Modified", self._http_ts(last_mod_dt))

        if ("Range" in self.request.headers or file_size > (1024 * 1024)):
            self.add_header("Accept-Ranges", "bytes")
            range_def = f"{start_offset}-{end_offset}/{file_size}"
            self.add_header("Content-Range", f"bytes {range_def}")

        await self.send_headers()

        with open(file_path, "rb") as f:
            f.seek(start_offset)
            total_sent = 0
            while (total_sent < content_len):
                rlen = min(IO_SIZE, content_len - total_sent)
                data = f.read(rlen)
                data_len = len(data)
                if (data_len > 0):
                    self.writer.write(data)
                    await self.writer.drain()
                    total_sent += data_len
                else:
                    break

    async def send_headers(self) -> None:

        if (self.code in http.client.responses):
            code_string = http.client.responses[self.code]
        else:
            code_string = "unknown"

        response = f"{self.request.request_version} {self.code} {code_string}\r\n"

        if ("Server" not in self.headers):
            self.add_header("Server", self.server)
        if ("Date" not in self.headers):
            self.add_header("Date", self._http_ts(datetime.utcnow()))

        for h in self.headers:
            response += h + "\r\n"

        response += "\r\n"

        self.writer.write(response.encode("utf-8"))
        await self.writer.drain()
        self.headers_sent = True


AsyncHandler = Callable[..., Awaitable[None]]
AsyncStaticHandler = Callable[[AsyncHttpRequest], Awaitable[None]]


class AsyncHttpRoute():

    def __init__(self, command: str, path: str, handler: Callable, mime_type: str = "", cache_timeout: int = 0) -> None:
        self.command = command
        self.path = path
        self.handler = handler
        self.mime_type = mime_type
        self.args: List[inspect.Parameter] = self._find_requirements()
        self.cache_timeout = cache_timeout

    def _find_requirements(self) -> List[inspect.Parameter]:

        args = []
        sig = inspect.signature(self.handler)

        for p in sig.parameters:
            args.append(sig.parameters[p])

        return args

    def _build_args(self, request: AsyncHttpRequest, in_args: AsyncHttpArgs) -> list:

        args = []

        for a in self.args:

            mandatory = (a.default == inspect.Parameter.empty)

            if (a.annotation == type(request)):
                a = request
            elif (a.annotation == type(1)):
                a = in_args.get_int(a.name,
                                    default=a.default,
                                    mandatory=mandatory)
            elif (a.annotation == type("")):
                a = in_args.get(a.name,
                                default=a.default,
                                mandatory=mandatory)
            elif (a.annotation == type(1.1)):
                a = in_args.get_float(a.name,
                                      default=a.default,
                                      mandatory=mandatory)
            elif (issubclass(a.annotation, AsyncHttpURL)):
                a = in_args.get_url(a.name,
                                    default=a.default,
                                    mandatory=mandatory)
            else:
                raise AsyncHttpNotImplemented(
                    "unknown type: " + str(a.annotation))

            args.append(a)

        return args

    async def _build_post_args(self, request: AsyncHttpRequest) -> list:

        args = await request.read_json_as_args()
        return self._build_args(request, args)

    ############################################################################
    # PUBLIC
    ############################################################################

    async def call(self, request: AsyncHttpRequest) -> None:

        if (self.command == "GET"):
            args = self._build_args(request, request.args)
        elif (self.command == "POST"):
            args = await self._build_post_args(request)
        else:
            raise AsyncHttpNotImplemented("unknown command: " + self.command)

        await self.handler(*args)


class AsyncHttpCache(StreamWriter):
    def __init__(self, writer: StreamWriter) -> None:
        self.birth_ts = time.time()
        self.writer = writer
        self.cache = io.BytesIO()

    def age(self) -> float:
        return time.time() - self.birth_ts

    def write(self, data: bytes) -> None:
        self.cache.write(data)
        self.last_update = time.time()
        self.writer.write(data)

    async def drain(self) -> None:
        await self.writer.drain()

    async def flush_to(self, writer: StreamWriter) -> None:
        self.cache.seek(0)

        while (True):
            data = self.cache.read(IO_SIZE)

            if (len(data) > 0):
                writer.write(data)
                await writer.drain()
            else:
                break


class AsyncHttpServer():
    def __init__(self, addr: str = "0.0.0.0", port: int = 8080, log_file: Optional[str] = None, verbose: bool = False) -> None:
        self.addr = addr
        self.port = port
        self.routes: List[AsyncHttpRoute] = []
        self.static_route: Optional[AsyncStaticHandler] = None
        self.cache_lock = asyncio.Lock()
        self.cache = {}
        self.cache_enabled = True

        self.logger = AsyncLogger(log_file, verbose=verbose)

    async def _read_header(self, reader: StreamReader) -> bytes:

        raw_req = b''

        while (True):
            data = await reader.readline()
            data_len = len(data)

            if (0 == data_len):
                raise AsyncHttpBadRequest("Empty request")

            raw_req += data

            if (data_len == 2):
                break

        return raw_req

    # redo find_route but allow for regex in the path
    def _find_route(self, req: HttpRequest) -> Optional[AsyncHttpRoute]:

        content_type = req.headers.get("Content-Type", "")
        q = urllib.parse.urlparse(req.path)

        for route in self.routes:
            if (route.command == req.command and re.match(route.path, q.path)):
                if (route.mime_type != ""):
                    if (content_type == route.mime_type):
                        return route
                else:
                    return route

        return None

    async def _request_handler(self, handler: AsyncHttpRequest, header_data: bytes) -> None:

        try:
            req = HttpRequest(header_data)
            handler._init_request(req)
        except Exception:
            raise AsyncHttpBadRequest("Invalid request")

        self.logger.log(req.path)

        route = self._find_route(req)

        if (True == self.cache_enabled and route is not None and route.cache_timeout > 0):

            cache_miss = True  # assume that it won't work

            async with self.cache_lock:
                if (req.path in self.cache):
                    cache = self.cache[req.path]

                    # we have a cache entry. Is it expired?
                    if (route.cache_timeout > cache.age()):
                        await cache.flush_to(handler.writer)
                        handler.headers_sent = True
                        cache_miss = False
                        self.logger.log(f"{req.path} was cached")
                    else:
                        del self.cache[req.path]

            # outside of the lock
            if (True == cache_miss):

                #
                # populating the entry
                #
                new_cache = AsyncHttpCache(handler.get_writer())
                handler.set_writer(new_cache)
                await route.call(handler)

                #
                # Cache is populated. Reclain the lock and update the but
                # don't assume it'll work since we could have served the
                # same request while populating
                #
                async with self.cache_lock:
                    if (req.path not in self.cache):
                        self.cache[req.path] = new_cache

        elif (route is not None):
            await route.call(handler)
        elif (self.static_handler is not None):
            await self.static_handler(handler)
        else:
            raise AsyncHttpNotFound(f"{req.path} not found")

    async def _client_handler(self, reader: StreamReader, writer: StreamWriter) -> None:

        peer = writer.get_extra_info("peername")
        sockfd = writer.get_extra_info("socket").fileno()

        peer_info = f"{peer[0]}:{peer[1]} fd={sockfd}"

        self.logger.log(f"Connection from  {peer_info}")

        handler = AsyncHttpRequest(reader, writer)

        try:

            while (True):

                header_data = await self._read_header(reader)

                try:
                    await self._request_handler(handler, header_data)

                # can't send anyting back to the client
                except ConnectionResetError:
                    break
                except BrokenPipeError:
                    self.logger.log(f"Broken pipe ({peer_info})")
                    break
                # we can send something to the client here
                except AsyncHttpException as e:
                    self.logger.log(e)
                    handler.code = e.code
                    handler.error_message = e.message
                # This should be handled
                except Exception as e:
                    self.logger.exception(e)
                    handler.code = 500
                    handler.error_message = str(e)

                if (handler.code < 200 or handler.code > 299):
                    if (handler.error_message is not None):
                        await handler.send_error(handler.error_message)

                # headers include the http status code
                if (False == handler.headers_sent):
                    await handler.send_headers()
                await writer.drain()

                if (handler.code < 200 or handler.code > 299):
                    break
                elif (False == handler.keep_alive):
                    break

        except AsyncHttpBadRequest as e:
            self.logger.log(f"Bad Request ({e})")
        except ConnectionResetError:
            self.logger.log(f"Lost connection ({peer_info})")
        except BrokenPipeError:
            self.logger.log(f"Broken pipe ({peer_info})")
        except Exception as e:
            self.logger.exception(e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except ConnectionResetError:
                self.logger.log(f"Lost connection ({peer_info})")
            except BrokenPipeError:
                self.logger.log(f"Broken pipe ({peer_info})")
            except Exception as e:
                self.logger.exception(e)

    ############################################################################
    # PUBLIC
    ############################################################################

    def disable_caching(self) -> None:
        self.cache_enabled = False

    def post(self, path: str, handler: AsyncHandler, mime_type: str = "", cache_timeout: int = 0) -> AsyncHttpRoute:
        return AsyncHttpRoute("POST", path, handler, mime_type, cache_timeout)

    def get(self, path: str, handler: AsyncHandler, cache_timeout: int = 0) -> AsyncHttpRoute:
        return AsyncHttpRoute("GET", path, handler, "", cache_timeout)

    def set_static_route(self, handler: AsyncHandler) -> None:
        self.static_handler = handler

    def add_routes(self, routes: List[AsyncHttpRoute]) -> None:
        self.routes.extend(routes)

    async def server_forever(self) -> None:
        server = await asyncio.start_server(self._client_handler, self.addr, self.port)
        self.logger.log("Server is ready")
        async with server:
            await server.serve_forever()
