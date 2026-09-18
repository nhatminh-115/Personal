"""Regression tests for exact project memory matching with special SQL wildcard characters."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.memory.service import SQLMemoryService


@pytest.mark.asyncio
async def test_project_memory_exact_lookup_wildcard_resistance(test_db_session: AsyncSession):
    """
    Ensure project memory retrieval uses exact match on project_name and does not
    treat '%' or '_' as wildcards or confuse prefix matches like 'Atlas' and 'Atlas_V2'.
    """
    mem_service = SQLMemoryService(test_db_session)

    # 1. Store memories in projects with overlapping prefix or wildcard characters
    await mem_service.store_project_memory(
        project_name="Atlas",
        key="version",
        content="Atlas uses Python 3.12",
    )
    await mem_service.store_project_memory(
        project_name="Atlas_V2",
        key="version",
        content="Atlas_V2 uses Python 3.13",
    )
    await mem_service.store_project_memory(
        project_name="100%_Coverage",
        key="goal",
        content="Goal is 100% coverage",
    )
    await mem_service.store_project_memory(
        project_name="1009_Coverage",
        key="goal",
        content="Goal is 1009 items",
    )

    # 2. Verify 'Atlas' only returns memories for 'Atlas', never 'Atlas_V2'
    atlas_mems = await mem_service.get_project_memories("Atlas")
    assert len(atlas_mems) == 1
    assert atlas_mems[0].content == "Atlas uses Python 3.12"
    assert atlas_mems[0].project_name == "Atlas"

    # 3. Verify 'Atlas_V2' only returns memories for 'Atlas_V2'
    atlas_v2_mems = await mem_service.get_project_memories("Atlas_V2")
    assert len(atlas_v2_mems) == 1
    assert atlas_v2_mems[0].content == "Atlas_V2 uses Python 3.13"
    assert atlas_v2_mems[0].project_name == "Atlas_V2"

    # 4. Verify '100%_Coverage' exact match does not match '1009_Coverage'
    coverage_mems = await mem_service.get_project_memories("100%_Coverage")
    assert len(coverage_mems) == 1
    assert coverage_mems[0].content == "Goal is 100% coverage"
    assert coverage_mems[0].project_name == "100%_Coverage"
