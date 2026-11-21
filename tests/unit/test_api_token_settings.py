"""Validation coverage for the optional shared API token setting."""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.settings import Settings


def test_api_token_can_be_disabled_with_none_or_empty_string():
    assert Settings(_env_file=None, AURA_API_TOKEN=None).AURA_API_TOKEN is None
    assert Settings(_env_file=None, AURA_API_TOKEN="").AURA_API_TOKEN is None


@pytest.mark.parametrize(
    "token",
    [
        "x" * 31,
        "x" * 32 + " ",
        "x" * 16 + "\t" + "x" * 16,
    ],
)
def test_api_token_rejects_weak_or_whitespace_values(token: str):
    with pytest.raises(ValidationError, match="AURA_API_TOKEN"):
        Settings(_env_file=None, AURA_API_TOKEN=token)


def test_api_token_is_validated_and_kept_as_a_masked_secret():
    token = "aura-test-token-" + "x" * 32

    configured = Settings(_env_file=None, AURA_API_TOKEN=token)

    assert isinstance(configured.AURA_API_TOKEN, SecretStr)
    assert configured.AURA_API_TOKEN.get_secret_value() == token
    assert token not in repr(configured.AURA_API_TOKEN)
