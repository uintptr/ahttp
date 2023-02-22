#!/usr/bin/env python3
from ahttp import AsyncHttpServer, AsyncHttpRequest
import sys
import os
import asyncio

# add the pkg in the search path since it's probably not installed
script_root = os.path.dirname(os.path.abspath(sys.argv[0]))
sys.path.append(os.path.join(script_root, "..", ".."))


class SampleHttpHandler:
    def __init__(self) -> None:
        script_root = os.path.dirname(os.path.abspath(sys.argv[0]))

        self.www_root = os.path.join(script_root, "www")

    async def static_handler(self, req: AsyncHttpRequest) -> None:

        fn = os.path.abspath(req.path)[1:]

        if (fn == ""):
            fn = "index.html"

        file_path = os.path.join(self.www_root, fn)

        await req.send_file(file_path)

    async def api_test(self, req: AsyncHttpRequest, flag: int) -> None:

        if (flag == 1234):
            message = {"password": "p4ssword"}
            await req.send_as_json(message)
        else:
            req.set_status(404)


async def run_server() -> None:

    handler = SampleHttpHandler()

    server = AsyncHttpServer(verbose=True)

    api_list = [
        server.get("/api/test", handler.api_test)
    ]

    server.add_routes(api_list)
    server.set_static_route(handler.static_handler)

    await server.server_forever()


def main() -> int:

    status = 1

    try:
        asyncio.run(run_server())
        status = 0
    except KeyboardInterrupt:
        status = 0

    return status


if __name__ == '__main__':
    status = main()

    if status != 0:
        sys.exit(status)
