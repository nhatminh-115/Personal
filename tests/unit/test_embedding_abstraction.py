"""Unit tests for the provider-neutral embedding abstraction layer."""

import pytest
from app.memory.embeddings.base import EmbeddingRequest
from app.memory.embeddings.mock_provider import MockEmbeddingProvider
from app.memory.embeddings.router import (
    EmbeddingModelMismatchError,
    EmbeddingRouter,
)


@pytest.mark.asyncio
async def test_mock_embedding_provider_deterministic_generation():
    """Verify that identical texts produce identical vectors and different texts produce different vectors."""
    provider = MockEmbeddingProvider(dimension=1536, model_name="test-mock-v1")
    assert provider.name == "mock"
    assert provider.dimension == 1536
    assert provider.model_name == "test-mock-v1"

    req1 = EmbeddingRequest(texts=["Atlas uses Python 3.12"])
    res1 = await provider.embed(req1)
    assert res1.dimension == 1536
    assert res1.model == "test-mock-v1"
    assert len(res1.embeddings) == 1
    assert len(res1.embeddings[0]) == 1536

    # Identical query produces identical vector
    q_vec = await provider.embed_query("Atlas uses Python 3.12")
    assert q_vec == res1.embeddings[0]

    # Different text produces different vector
    other_vec = await provider.embed_query("Completely unrelated topic about astronomy")
    assert other_vec != q_vec


@pytest.mark.asyncio
async def test_embedding_router_dimension_validation_and_mismatch():
    """Verify that EmbeddingRouter detects and rejects vector dimension mismatches."""
    mock_1536 = MockEmbeddingProvider(dimension=1536, model_name="mock-1536")
    router = EmbeddingRouter(
        providers={"mock": mock_1536},
        default_provider="mock",
    )

    assert router.current_dimension == 1536
    assert router.current_model_name == "mock-1536"

    # Valid vector check
    valid_vec = [0.1] * 1536
    router.validate_vector_compatibility(valid_vec, model_name="mock-1536")

    # Wrong dimension must raise EmbeddingModelMismatchError
    invalid_dim_vec = [0.1] * 512
    with pytest.raises(EmbeddingModelMismatchError, match="dimension 512 does not match"):
        router.validate_vector_compatibility(invalid_dim_vec, model_name="mock-1536")

    # Mismatched model name must raise EmbeddingModelMismatchError
    with pytest.raises(EmbeddingModelMismatchError, match="Re-embedding required"):
        router.validate_vector_compatibility(valid_vec, model_name="old-legacy-model-v0")
