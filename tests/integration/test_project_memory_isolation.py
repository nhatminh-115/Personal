"""Integration tests for project memory scoping and isolation through the /v1/chat endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_project_memory_isolation_across_projects(async_client: AsyncClient):
    """
    Verify complete project memory isolation:
    - Atlas memories do not leak to Titan.
    - Titan memories do not leak to Atlas.
    - Sessions without project_name do not receive any project memory.
    - Memory survives across sessions for the same project.
    """
    # 1. Teach Project Atlas its Python version
    sess_atlas_1 = "sess-atlas-teach"
    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": sess_atlas_1,
            "message": "Please remember that Project Atlas uses Python 3.12",
            "project_name": "Atlas",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # 2. Teach Project Titan its Go version
    sess_titan_1 = "sess-titan-teach"
    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": sess_titan_1,
            "message": "Please remember that Project Titan uses Go 1.22",
            "project_name": "Titan",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # 3. Query Project Atlas: must know Python 3.12, must NEVER mention Go 1.22
    sess_atlas_2 = "sess-atlas-query"
    resp_atlas = await async_client.post(
        "/v1/chat",
        json={
            "session_id": sess_atlas_2,
            "message": "What version of Python does this project use?",
            "project_name": "Atlas",
        },
    )
    assert resp_atlas.status_code == 200
    data_atlas = resp_atlas.json()
    assert "Python 3.12" in data_atlas["response"]
    assert "Go 1.22" not in data_atlas["response"]

    # 4. Query Project Titan: must know Go 1.22, must NEVER mention Python 3.12
    sess_titan_2 = "sess-titan-query"
    resp_titan = await async_client.post(
        "/v1/chat",
        json={
            "session_id": sess_titan_2,
            "message": "What language and version does this project use?",
            "project_name": "Titan",
        },
    )
    assert resp_titan.status_code == 200
    data_titan = resp_titan.json()
    assert "Go 1.22" in data_titan["response"]
    assert "Python 3.12" not in data_titan["response"]

    # 5. Query without any project_name: must NEVER receive Atlas or Titan facts
    sess_general = "sess-general-query"
    resp_general = await async_client.post(
        "/v1/chat",
        json={
            "session_id": sess_general,
            "message": "What language and version does this project use?",
            "project_name": None,
        },
    )
    assert resp_general.status_code == 200
    data_gen = resp_general.json()
    assert "Python 3.12" not in data_gen["response"]
    assert "Go 1.22" not in data_gen["response"]
