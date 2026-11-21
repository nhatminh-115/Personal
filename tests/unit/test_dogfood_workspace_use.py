from urllib.parse import parse_qs

import pytest

from scripts import dogfood_workspace_use


@pytest.mark.parametrize("project_name", ["aura-ci", "aura-a8-dogfood"])
def test_a8_acceptance_allows_only_named_compose_projects(project_name):
    dogfood_workspace_use.validate_test_project(project_name)


@pytest.mark.parametrize("project_name", ["", "aura", "personal", "aura-a6-dogfood"])
def test_a8_acceptance_rejects_unlisted_compose_projects(project_name):
    with pytest.raises(ValueError, match="named CI and local dogfood projects"):
        dogfood_workspace_use.validate_test_project(project_name)


@pytest.mark.parametrize("url", ["http://127.0.0.1:18001", "http://localhost:18001"])
def test_a8_acceptance_accepts_loopback_api_url(url):
    dogfood_workspace_use.validate_api_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:18001",
        "http://example.test",
        "http://user:secret@localhost:18001",
        "http://localhost:18001/#fragment",
    ],
)
def test_a8_acceptance_rejects_nonlocal_or_credential_bearing_api_url(url):
    with pytest.raises(ValueError, match="local Compose API"):
        dogfood_workspace_use.validate_api_url(url)


def test_cursor_pagination_preserves_search_filter_and_walks_until_expected_ids(monkeypatch):
    calls = []
    pages = [
        ([{"id": "older-result"}], {"X-Next-Cursor": "cursor-1"}),
        ([{"id": "expected-result"}], {}),
    ]

    def fake_call(api_base_url, api_token, method, path, body=None, *, expected_status=200):
        calls.append((method, path))
        return pages.pop(0)

    monkeypatch.setattr(dogfood_workspace_use, "_call", fake_call)
    items = dogfood_workspace_use._cursor_collection(
        "http://127.0.0.1:18001",
        "synthetic-token",
        "/v1/workspace/library?q=needle",
        page_size=1,
        minimum_count=1,
        expected_ids={"expected-result"},
    )

    assert [item["id"] for item in items] == ["older-result", "expected-result"]
    assert calls[0][1].startswith("/v1/workspace/library?")
    assert parse_qs(calls[0][1].split("?", 1)[1]) == {"q": ["needle"], "page_size": ["1"]}
    second_params = parse_qs(calls[1][1].split("?", 1)[1])
    assert second_params == {"q": ["needle"], "page_size": ["1"], "cursor": ["cursor-1"]}


def test_cursor_pagination_fails_if_cursor_repeats(monkeypatch):
    def repeated_cursor(*_args, **_kwargs):
        return ([{"id": "another-result"}], {"X-Next-Cursor": "same-cursor"})

    monkeypatch.setattr(dogfood_workspace_use, "_call", repeated_cursor)
    with pytest.raises(RuntimeError, match="repeated a pagination cursor"):
        dogfood_workspace_use._cursor_collection(
            "http://127.0.0.1:18001",
            "synthetic-token",
            "/v1/workspace/library?q=needle",
            page_size=1,
            minimum_count=2,
            expected_ids={"not-present"},
        )
