"""X (Twitter) Cookie API — FastAPI mirror of X API v2.

Mounts router modules per resource family. App-wide concerns (lifespan,
OpenAPI auto-tagging, security headers) live in `app.openapi_tags` +
`app.security`. Helpers split into `app.config`, `app.auth`, `app.clients`,
`app.responses`, `app.client_pool`, `app.response_cache`, `app.retry`.

Run:
    uvicorn main:app --host 127.0.0.1 --port 8000

Environment variables (optional):
    ADMIN_TOKEN          — required header value untuk /admin/stats
    PROXY_LIST           — comma-separated proxy URLs (rotates per request)
    ALLOWED_ORIGINS      — CORS allowlist (comma-separated)
    ENABLE_RAW           — 0 to disable ?raw=1 in prod (default 1)
    MAX_BODY_SIZE        — bytes (default 1048576 = 1 MB)
    RESPONSE_CACHE_TTL   — seconds (default 30; 0 disables)
    RETRY_MAX_ATTEMPTS   — default 3
    CLIENT_POOL_MAX      — max pooled sessions (default 50)
    CLIENT_POOL_TTL      — pool entry TTL seconds (default 600)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from playwright_search import PlaywrightPool

from app.client_pool import ClientPool
from app.openapi_tags import OPENAPI_TAGS, install_auto_tagger
from app.routers import (
    birdwatch,
    bookmarks,
    communities,
    dm,
    infra,
    lists,
    media,
    spaces,
    timelines,
    trends,
    tweets,
    users,
)
from app.security import install_security_middleware

DOCS_UI_DIR = Path(__file__).parent / "docs-ui"
DOCS_UI_DIST = DOCS_UI_DIR / "dist"
# Auto-prefer pre-compiled dist/ (esbuild output, no Babel) kalau ada.
DOCS_UI_SERVE = DOCS_UI_DIST if DOCS_UI_DIST.is_dir() else DOCS_UI_DIR


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup pre-warm + shutdown cleanup.

    Pre-warm Playwright browser supaya request pertama tidak nunggu Chromium
    init (~2-3s). Browser tetap satu shared instance.
    """
    # Pre-warm di background — non-blocking startup.
    import asyncio
    asyncio.create_task(PlaywrightPool.get().warmup())
    yield
    await PlaywrightPool.get().close()
    await ClientPool.get().close_all()


app = FastAPI(
    title="X (Twitter) Cookie API",
    description=(
        "Mirror X API v2 pakai cookie `auth_token` (web session) — tanpa OAuth2 / dev portal.\n\n"
        "**Auth:** Header `Authorization: Bearer <auth_token>` atau Query `?auth_token=...`.\n"
        "**Raw payload:** Tambahkan `?raw=1` untuk bypass formatter v2 → dapat payload mentah X "
        "(disabled di prod via `ENABLE_RAW=0`).\n\n"
        "Endpoint X Enterprise tier (Streams, Compliance, Webhooks, Account Activity, "
        "Search Counts/All, Insights, Analytics, News, Media library) sudah dihapus karena "
        "butuh OAuth2 app-only bearer + subscription dev portal."
    ),
    version="2.3.0",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)

# Mount routers — order doesn't matter, but listed by tag priority.
app.include_router(infra.router)
app.include_router(users.router)
app.include_router(tweets.router)
app.include_router(timelines.router)
app.include_router(lists.router)
app.include_router(bookmarks.router)
app.include_router(communities.router)
app.include_router(birdwatch.router)
app.include_router(dm.router)
app.include_router(spaces.router)
app.include_router(trends.router)
app.include_router(media.router)

install_security_middleware(app)
install_auto_tagger(app)


@app.exception_handler(StarletteHTTPException)
async def _api_404_handler(request, exc):
    """Return JSON 404 untuk path API; biarin static mount handle path lain.

    Tanpa handler ini, /2/typo dan /login (POST salah method) bisa "kena"
    StaticFiles fallback ke index.html — confusing buat API client.
    """
    p = request.url.path
    if exc.status_code == 404 and (p.startswith("/2/") or p in ("/login", "/info", "/search", "/admin/stats", "/docs", "/openapi.json", "/redoc")):
        return JSONResponse(
            status_code=404,
            content={
                "errors": [{
                    "title": "Not Found",
                    "detail": f"no API route matches {request.method} {p}",
                    "type": "not_found",
                    "status": 404,
                }]
            },
        )
    # Default: re-raise untuk dapet HTML dari static mount, atau
    # default Starlette response.
    return await http_exception_handler(request, exc)


# Static docs-ui at `/`. Prefer pre-compiled dist/ kalau ada (no Babel) —
# fallback ke source files (in-browser babel-standalone) untuk dev.
if DOCS_UI_SERVE.is_dir():
    from starlette.responses import Response as StarletteResponse

    class CachedStaticFiles(StaticFiles):
        """StaticFiles + Cache-Control headers untuk asset deterministik.

        - HTML (index.html): no-cache, must-revalidate (always-fresh shell)
        - JSX/JS/CSS/data.js: 1 hour public cache (re-validate via etag)
        - bundle.js (esbuild output): immutable 1 year (versioned via build hash)
        """
        async def get_response(self, path: str, scope):
            response = await super().get_response(path, scope)
            if isinstance(response, StarletteResponse) and response.status_code == 200:
                # path "" / "." / "index.html" semua resolve ke index.html
                if path in ("", ".", "/", "index.html") or path.endswith(".html"):
                    response.headers["Cache-Control"] = "no-cache, must-revalidate"
                elif path.endswith("bundle.js"):
                    # esbuild bundle: deterministic, safe long cache.
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                else:
                    # JSX, CSS, data.js — re-validate cepat via etag, 1 jam fresh.
                    response.headers["Cache-Control"] = "public, max-age=3600"
            return response

    app.mount("/", CachedStaticFiles(directory=str(DOCS_UI_SERVE), html=True), name="docs-ui")


if __name__ == "__main__":
    import os
    import sys
    import uvicorn

    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    if workers > 1:
        sys.stderr.write(
            "WARNING: Xapi caches (SessionStore, ResponseCache, ContextPool) "
            "are per-worker in-memory. With WEB_CONCURRENCY>1 each worker has "
            "duplicate cache → ~Nx memory + ~N-1x cache miss antar worker. "
            "Recommended: workers=1 + horizontal scale via reverse proxy/multiple instances.\n"
        )
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=workers)
