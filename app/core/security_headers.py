# app/core/security_headers.py

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Sets baseline security response headers. TLS termination (Caddy, ALB)
    doesn't add these on its own — deploy/Caddyfile is a bare reverse_proxy, and ALB
    listeners don't inject them either — so the app has to.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"

        # Only advertise HSTS when the request actually arrived over HTTPS —
        # asserting it over plain HTTP would tell browsers to force HTTPS on
        # this host, breaking local dev and the no-domain plain-HTTP prod
        # path. request.url.scheme reflects uvicorn's own listener (always
        # "http" here — TLS is terminated upstream by Caddy/ALB), so this
        # checks X-Forwarded-Proto instead, which both already set.
        if request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"

        return response
