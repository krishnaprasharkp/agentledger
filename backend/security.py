import asyncio
from math import ceil
from secrets import compare_digest
from threading import Lock
from time import monotonic

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from invoice_agent.pdf_extractor import MAX_PDF_SIZE

MAX_REQUEST_BYTES = MAX_PDF_SIZE + 64 * 1024
DEMO_PREVIEW_PATH = "/demo/forecasts/preview"
DEMO_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


class PreviewBudget:
    """One shared budget for all visitors in a single Uvicorn worker."""

    burst = 12
    seconds_per_token = 2

    def __init__(self):
        self.tokens = float(self.burst)
        self.updated = monotonic()
        self.lock = Lock()

    def consume(self) -> int:
        with self.lock:
            now = monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.updated) / self.seconds_per_token)
            self.updated = now
            if self.tokens < 1:
                return ceil((1 - self.tokens) * self.seconds_per_token)
            self.tokens -= 1
            return 0


class PublicDemoSecurity:
    def __init__(self, app):
        self.app = app
        self.budget = PreviewBudget()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        preview = scope["path"] == DEMO_PREVIEW_PATH

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = DEMO_CSP
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                if preview:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        if preview and scope["method"] == "POST":
            # Render's transport peer is a proxy. No request header participates in the budget.
            wait = self.budget.consume()
            if wait:
                await JSONResponse(
                    {"detail": "Too many forecast previews. Try again shortly."},
                    status_code=429, headers={"Retry-After": str(wait)},
                )(scope, receive, secure_send)
                return
            content_type = Headers(scope=scope).get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json" and not (
                content_type.startswith("application/") and content_type.endswith("+json")
            ):
                await JSONResponse(
                    {"detail": "Send forecast previews as JSON."}, status_code=415,
                )(scope, receive, secure_send)
                return
        await self.app(scope, receive, secure_send)


class WorkspaceSecurity:
    def __init__(self, app, key: str = "", require_key: bool = False, json_limit: int = 64 * 1024,
                 body_timeout: float | None = None):
        self.app = app
        self.key = key.encode()
        self.require_key = require_key
        self.json_limit = json_limit
        self.body_timeout = body_timeout

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
                if protected or path == DEMO_PREVIEW_PATH:
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
        oversized = False
        try:
            async with asyncio.timeout(self.body_timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > limit:
                        oversized = True
                        break
                    body.extend(chunk)
                    if not message.get("more_body"):
                        break
        except TimeoutError:
            await JSONResponse({"detail": "Request body did not arrive in time."}, status_code=408)(
                scope, receive, send
            )
            return
        if oversized:
            await JSONResponse({"detail": "Request body exceeds the size limit."}, status_code=413)(
                scope, receive, send
            )
            return

        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
