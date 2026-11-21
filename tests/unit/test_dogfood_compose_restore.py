"""Safety guards for the destructive A6 Docker acceptance runner."""

import pytest

from scripts.dogfood_compose_restore import validate_test_project, validate_workspace_path


@pytest.mark.parametrize("project_name", ["aura-ci", "aura-a6-dogfood"])
def test_clean_volume_recreation_requires_an_allowlisted_test_project(project_name):
    validate_test_project(project_name, "1")


@pytest.mark.parametrize(
    ("project_name", "allow_volume_recreate"),
    [
        ("", "1"),
        ("aura-personal", "1"),
        ("aura-ci", ""),
        ("aura-a6-dogfood", "true"),
    ],
)
def test_clean_volume_recreation_rejects_unapproved_projects(project_name, allow_volume_recreate):
    with pytest.raises(ValueError):
        validate_test_project(project_name, allow_volume_recreate)


@pytest.mark.parametrize("value", ["notes/a6.txt", "aura-compose-smoke.txt"])
def test_workspace_path_accepts_safe_relative_posix_paths(value):
    assert validate_workspace_path(value).as_posix() == value


@pytest.mark.parametrize("value", ["", "../outside", "notes/../../outside", "/absolute", "C:/outside", "notes\\outside"])
def test_workspace_path_rejects_traversal_and_absolute_paths(value):
    with pytest.raises(ValueError):
        validate_workspace_path(value)
