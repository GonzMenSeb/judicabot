from __future__ import annotations

import mimetypes

from starlette.datastructures import MutableHeaders
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'"
CACHE_INMUTABLE = "public, max-age=31536000, immutable"
CACHE_REVALIDAR = "no-cache"
PREFIJOS_SIN_CSP = ("/docs", "/redoc")
SIN_GZIP = (
    *DEFAULT_EXCLUDED_CONTENT_TYPES,
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/x-icon",
    "image/vnd.microsoft.icon",
    "font/woff2",
)

for _tipo, _extension in (("font/woff2", ".woff2"), ("application/manifest+json", ".webmanifest")):
    mimetypes.add_type(_tipo, _extension)


class CabecerasEstaticas:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        ruta = scope["path"]

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                cabeceras = MutableHeaders(scope=mensaje)
                if "cache-control" not in cabeceras:
                    exitosa = mensaje["status"] in (200, 206, 304)
                    cabeceras["Cache-Control"] = (
                        CACHE_INMUTABLE if exitosa and ruta.startswith("/assets/") else CACHE_REVALIDAR
                    )
                if cabeceras.get("content-type", "").startswith("text/html") and not ruta.startswith(PREFIJOS_SIN_CSP):
                    cabeceras["Content-Security-Policy"] = CSP
            await send(mensaje)

        await self.app(scope, receive, enviar)
