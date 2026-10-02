"""Zero-invocation routing constraints smoke against the configured model catalog.

GET /v1/models performs its normal provider discovery snapshot, which can make
local model-list HTTP requests. The script does not call explicit refresh or
capability-probe endpoints and never invokes a model. Unknown provider/model
metadata stays unknown.
"""
import asyncio
import json
import os
from pathlib import Path
import uuid
from typing import Any, Mapping


def live_environment_error(_environ: Mapping[str, str] | None = None) -> str | None:
    """This scenario only reads the model catalog and invokes zero model calls."""
    return None


def configured_model(providers: list[dict[str, Any]], *, local: bool) -> tuple[str, str] | None:
    """Choose only a currently available model whose provider kind is explicit."""
    accepted_kinds = {"local"} if local else {"cloud", "hosted"}
    for provider in providers:
        if not isinstance(provider, dict) or provider.get("available") is not True:
            continue
        if provider.get("kind") not in accepted_kinds:
            continue
        models = provider.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if isinstance(model, dict) and isinstance(model.get("id"), str) and model["id"]:
                return str(provider.get("id", "")), model["id"]
    return None


def _draft(name: str, model: str, privacy: str, fallback: str) -> dict[str, Any]:
    provider, model_id = model.split(":", 1)
    return {
        "name": name,
        "version": 1,
        "is_active": True,
        "is_default": False,
        "global_privacy_policy": privacy,
        "global_fallback_policy": fallback,
        "cost_preference": "normal",
        "latency_preference": "normal",
        "routes": {
            "root": {
                "model_override": model_id,
                "provider_override": provider,
                "reasoning": {"policy": "fixed", "effort": "low"},
                "privacy_policy": privacy,
                "fallback_policy": fallback,
            }
        },
    }


async def run_live_dogfood() -> None:
    error = live_environment_error()
    if error:
        print(f"ROUTING CONSTRAINTS DOGFOOD NOT EXECUTED — {error}")
        raise SystemExit(2)

    run_key = uuid.uuid4().hex[:12]
    data_dir = Path(".aura_dogfood").resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    from sqlalchemy.engine import URL
    database_url = URL.create("sqlite+aiosqlite", database=str(data_dir / f"routing-{run_key}.db")).render_as_string(hide_password=False)
    checkpoint_path = data_dir / f"routing-{run_key}-checkpoints.db"
    os.environ["DATABASE_URL"] = database_url
    os.environ["CHECKPOINT_DB_PATH"] = str(checkpoint_path)

    from app.core.settings import settings
    settings.DATABASE_URL = database_url
    settings.CHECKPOINT_DB_PATH = checkpoint_path
    from app.db import session as db_session
    db_session.configure_engine(database_url)
    from app.orchestrator.graph import init_checkpointer
    await init_checkpointer(checkpoint_path)

    from app.api.server import create_app, lifespan
    import httpx

    app = create_app()
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as client:
            catalog_response = await client.get("/v1/models")
            if catalog_response.status_code != 200:
                raise SystemExit(f"Model catalog request failed with HTTP {catalog_response.status_code}.")
            catalog = catalog_response.json()
            providers = catalog.get("providers", []) if isinstance(catalog, dict) else []
            local = configured_model(providers, local=True)
            cloud = configured_model(providers, local=False)
            if local is None:
                print("ROUTING CONSTRAINTS DOGFOOD NOT EXECUTED — no available provider is explicitly classified as local.")
                print("No explicit refresh, capability probe, installation, or model invocation was attempted; GET /v1/models performs its normal provider discovery.")
                raise SystemExit(2)
            if cloud is None:
                print("ROUTING CONSTRAINTS DOGFOOD NOT EXECUTED — no available provider is explicitly classified as cloud/hosted.")
                print("No model refresh, provider probe, installation, or invocation was attempted.")
                raise SystemExit(2)

            local_model = f"{local[0]}:{local[1]}"
            cloud_model = f"{cloud[0]}:{cloud[1]}"
            local_preview = await client.post("/v1/routing/preview", json={
                "role": "root",
                "context": {"privacy_requirement": "local_only", "fallback_policy": "none"},
                "profile_draft": _draft("Dogfood Local Only", local_model, "local_only", "none"),
            })
            cloud_preview = await client.post("/v1/routing/preview", json={
                "role": "root",
                "context": {"privacy_requirement": "public", "fallback_policy": "cloud_allowed"},
                "profile_draft": _draft("Dogfood Cloud Allowed", cloud_model, "public", "cloud_allowed"),
            })
            if local_preview.status_code != 200 or cloud_preview.status_code != 200:
                raise SystemExit(
                    f"Routing preview failed (local={local_preview.status_code}, cloud={cloud_preview.status_code}); "
                    "inspect structured server errors."
                )
            local_result, cloud_result = local_preview.json(), cloud_preview.json()

    report = {
        "scenario": "routing_local_privacy_and_cloud_allowed_preview",
        "catalog_provider_count": len(providers),
        "local_model_identity": local_model,
        "cloud_model_identity": cloud_model,
        "local_preview": {
            "provider": local_result.get("provider"),
            "model": local_result.get("model"),
            "privacy": local_result.get("privacy"),
            "fallback": local_result.get("fallback"),
            "winning_scope": local_result.get("winning_scope"),
            "warnings": local_result.get("warnings", []),
        },
        "cloud_preview": {
            "provider": cloud_result.get("provider"),
            "model": cloud_result.get("model"),
            "privacy": cloud_result.get("privacy"),
            "fallback": cloud_result.get("fallback"),
            "winning_scope": cloud_result.get("winning_scope"),
            "warnings": cloud_result.get("warnings", []),
        },
        "model_invocation": "none; both calls used zero-invocation /v1/routing/preview",
        "profile_persisted": False,
    }
    report["accepted"] = (
        local_result.get("provider") == local[0]
        and local_result.get("model") == local[1]
        and local_result.get("privacy") == "local_only"
        and local_result.get("fallback") == "none"
        and cloud_result.get("provider") == cloud[0]
        and cloud_result.get("model") == cloud[1]
        and cloud_result.get("privacy") == "public"
        and cloud_result.get("fallback") == "cloud_allowed"
        and local_result.get("winning_scope") == "draft"
        and cloud_result.get("winning_scope") == "draft"
    )
    output_dir = Path("artifacts/dogfood").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"routing-constraints-{uuid.uuid4().hex[:12]}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Audit artifact: {report_path}")
    if not report["accepted"]:
        raise SystemExit("Acceptance failed: exact catalog models did not preserve draft scope and policy.")
    print("ACCEPTANCE RESULT: configured local-only and cloud-allowed routes previewed with zero model calls.")


if __name__ == "__main__":
    asyncio.run(run_live_dogfood())
