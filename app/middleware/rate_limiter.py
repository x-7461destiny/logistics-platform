from app.dependencies import rate_limiter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        key = f"rate_limit:{request.client.host}"
        if await rate_limiter.is_rate_limited(key):
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        response = await call_next(request)
        return response
