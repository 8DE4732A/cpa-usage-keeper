"""FastAPI application factory with lifespan management."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from loguru import logger
from .config import Config, load_config
from .database import init_database, close_database
from .logging_config import configure_logging
from .auth.session import SessionManager
from .cpa.client import CPAClient
from .cpa.redis_queue import RedisQueueClient
from .service.sync import SyncService
from .backup import BackupWriter
from .poller.poller import PollerStatus, RedisDrain, MaintenanceRunner, BackupRunner
from .api.router import create_api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg: Config = app.state.cfg
    sync_service: SyncService = app.state.sync_service
    poller_status: PollerStatus = app.state.poller_status
    background_tasks: list[asyncio.Task] = []

    sync_service.detect_sync_mode()
    mode = sync_service.sync_mode
    logger.info(f"Starting background tasks, sync_mode={mode}")

    if mode == "redis":
        drain = RedisDrain(sync_service, cfg.redis_queue_idle_interval,
                           cfg.redis_queue_error_backoff, cfg.redis_metadata_sync_interval,
                           status=poller_status)
        app.state.active_poller = drain
        background_tasks.append(asyncio.create_task(drain.run()))
    else:
        logger.warning("Sync mode is not redis; no poller started")

    maintenance = MaintenanceRunner(sync_service)
    background_tasks.append(asyncio.create_task(maintenance.run()))

    if cfg.backup_enabled:
        writer = BackupWriter(cfg.backup_dir)
        backup_runner = BackupRunner(writer, cfg.sqlite_path, cfg.backup_interval,
                                      cfg.backup_retention_days)
        background_tasks.append(asyncio.create_task(backup_runner.run()))

    yield

    poller_status.running = False
    logger.info("Shutting down background tasks...")
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    close_database()
    logger.info("Application shutdown complete")


def create_app(config_file: str = "config.toml") -> FastAPI:
    """Create and configure the FastAPI application."""
    cfg = load_config(config_file)
    configure_logging(cfg)
    init_database(cfg)

    # Session manager
    session_manager = None
    if cfg.auth_enabled:
        session_manager = SessionManager(cfg.auth_session_ttl)

    # CPA clients
    cpa_client = CPAClient(cfg.cpa_base_url, cfg.cpa_management_key, cfg.request_timeout)
    redis_client = None
    if cfg.usage_sync_mode in ("auto", "redis"):
        redis_client = RedisQueueClient(
            cfg.cpa_base_url, cfg.redis_queue_addr, cfg.cpa_management_key,
            cfg.request_timeout, cfg.redis_queue_key, cfg.redis_queue_batch_size)

    # Sync service
    sync_service = SyncService(cfg, cpa_client, redis_client)

    # Poller status (shared between pollers and API)
    poller_status = PollerStatus()

    # Create app
    app = FastAPI(title="CPA Usage Keeper", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.sync_service = sync_service
    app.state.poller_status = poller_status
    app.state.active_poller = None  # set during lifespan

    # API router
    base_path = cfg.app_base_path or ""
    api_router = create_api_router(session_manager, cfg.auth_enabled, cfg.login_password,
                                    poller_status=poller_status, app=app)
    app.include_router(api_router, prefix=base_path)

    # Static files (frontend): prefer package-bundled assets, fall back to repo root for dev
    _pkg_static = Path(__file__).parent / "static"
    _repo_static = Path(__file__).parent.parent.parent / "static"
    static_dir = _pkg_static if _pkg_static.exists() else _repo_static
    if static_dir.exists():
        index_file = static_dir / "index.html"

        def _render_index() -> HTMLResponse:
            html = index_file.read_text(encoding="utf-8").replace(
                '"__APP_BASE_PATH__"', f'"{base_path}"'
            )
            return HTMLResponse(content=html)

        # SPA fallback: serve index.html for non-API, non-static routes
        @app.middleware("http")
        async def spa_fallback(request, call_next):
            response = await call_next(request)
            path = request.url.path
            if base_path:
                path = path.removeprefix(base_path)
            if (response.status_code == 404
                    and not path.startswith("/api/")
                    and not path.startswith("/healthz")
                    and "." not in path.split("/")[-1]):
                if index_file.exists():
                    return _render_index()
            return response

        mount_path = f"{base_path}/" if base_path else "/"
        # Serve index.html with base_path injected for root and SPA routes
        @app.get(base_path or "/", include_in_schema=False)
        @app.get(f"{base_path}/", include_in_schema=False)
        async def serve_index():
            return _render_index()

        app.mount(mount_path, StaticFiles(directory=str(static_dir), html=False), name="static")

    logger.info(f"CPA Usage Keeper started on port {cfg.app_port}, base_path='{cfg.app_base_path}'")
    return app
