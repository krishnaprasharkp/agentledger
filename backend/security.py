from secrets import compare_digest

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from invoice_agent.pdf_extractor import MAX_PDF_SIZE

MAX_REQUEST_BYTES = MAX_PDF_SIZE + 64 * 1024


class WorkspaceSecurity:
    def __init__(self, app, key: str = "", require_key: bool = False, json_limit: int = 64 * 1024):
        self.app = app
        self.key = key.encode()
        self.require_key = require_key
        self.json_limit = json_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"].rstrip("/")
        protected = path.startswith(("/events", "/invoices", "/analytics", "/portfolio", "/adapters"))
        headers = Headers(scope=scope)
        if protected and (self.key or self.require_key):
            supplied = headers.get("x-workspace-key", "").encode()
            if not self.key or not compare_digest(supplied, self.key):
                await JSONResponse({"detail": "Workspace key required."}, status_code=401)(scope, receive, send)
                return

        original_send = send

        async def secure_send(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["Referrer-Policy"] = "no-referrer"
                if protected or path == "/demo/forecasts/preview":
                    response_headers["Cache-Control"] = "no-store"
            await original_send(message)

        send = secure_send
        if scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        limit = MAX_REQUEST_BYTES if path in {"/invoices/upload", "/invoices/process"} else self.json_limit
        content_length = headers.get("content-length")
        if content_length and content_length.isascii() and content_length.isdecimal() and (
            len(content_length) > 10 or int(content_length) > limit
        ):
            await JSONResponse({"detail": "Request body exceeds the size limit."}, status_code=413)(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                await JSONResponse({"detail": "Request body exceeds the size limit."}, status_code=413)(
                    scope, receive, send
                )
                return
            body.extend(chunk)
            if not message.get("more_body"):
                break

        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
