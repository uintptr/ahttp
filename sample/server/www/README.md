# server

## Start the server

```
./server.py
```

## Query a static file (index.html)

```
curl -v http://localhost:8080
*   Trying 127.0.0.1:8080...
* Connected to localhost (127.0.0.1) port 8080 (#0)
> GET / HTTP/1.1
> Host: localhost:8080
> User-Agent: curl/7.87.0
> Accept: */*
>
* Mark bundle as not supporting multiuse
< HTTP/1.1 200 OK
< Content-Type: text/html
< Connection: keep-alive
< Cache-Control: no-cache
< Content-Length: 74
< Last-Modified: Tue, 21 Feb 2023 22:08:56 GMT
< Server: Python/3.11.2
< Date: Wed, 22 Feb 2023 03:10:38 GMT
<
<html>
    <body bgcolor="yellow">
        Hello World
    </body>
* Connection #0 to host localhost left intact
```

## Query the API

```
curl http://localhost:8080/api/test
{
    "message": "Missing argument: flag"
}
```

### Wrong flag
```
curl -v http://localhost:8080/api/test?flag=1111
*   Trying 127.0.0.1:8080...
* Connected to localhost (127.0.0.1) port 8080 (#0)
> GET /api/test?flag=1111 HTTP/1.1
> Host: localhost:8080
> User-Agent: curl/7.87.0
> Accept: */*
>
* Mark bundle as not supporting multiuse
< HTTP/1.1 404 Not Found
< Server: Python/3.11.2
< Date: Wed, 22 Feb 2023 03:12:25 GMT
* no chunk, no close, no size. Assume close to signal end
<
* Closing connection 0
```

### Good Flag

```
curl http://localhost:8080/api/test?flag=1234
{
    "password": "p4ssword"
}
```