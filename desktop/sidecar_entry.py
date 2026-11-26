"""Windows packaged entrypoint for the existing Kuractus API runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def resource_root() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else Path(__file__).resolve().parents[1]


def migrate() -> int:
    from alembic import command
    from alembic.config import Config

    root = resource_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")
    return 0


async def serve(host: str, port: int) -> None:
    import uvicorn
    from app.api.server import app

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False))
    server_task = asyncio.create_task(server.serve())
    shutdown_event = app.state.desktop_shutdown_event
    await shutdown_event.wait()
    server.should_exit = True
    await server_task


def main() -> int:
    parser = argparse.ArgumentParser(prog="aura-api")
    parser.add_argument("--desktop-migrate", action="store_true")
    parser.add_argument("--desktop-serve", action="store_true")
    parser.add_argument("--desktop-self-test", action="store_true")
    parser.add_argument("--desktop-backup", type=Path)
    parser.add_argument("--desktop-restore", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17890)
    args = parser.parse_args()

    if args.desktop_migrate:
        return migrate()
    if args.desktop_self_test:
        root = resource_root()
        required = [root / "alembic.ini", root / "migrations" / "env.py"]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise SystemExit(f"Packaged Kuractus runtime is incomplete: {', '.join(missing)}")
        from app.api.server import create_app

        app = create_app()
        if not any(route.path == "/v1/internal/desktop/shutdown" for route in app.routes):
            raise SystemExit("Desktop shutdown control is not registered; set DESKTOP_MODE=true for the packaged runtime.")
        print("Desktop API sidecar resources and runtime routes are present.")
        return 0
    if args.desktop_backup:
        from desktop.data_backup import create_backup

        print(json.dumps(create_backup(args.desktop_backup)))
        return 0
    if args.desktop_restore:
        from desktop.data_backup import restore_backup

        print(json.dumps(restore_backup(args.desktop_restore)))
        return 0
    if args.desktop_serve:
        asyncio.run(serve(args.host, args.port))
        return 0
    parser.error("Kuractus Desktop invokes this executable with a desktop mode.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
