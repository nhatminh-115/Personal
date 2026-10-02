import pytest

from app.db.models import WorkspaceObjectModel
from app.memory.context_compiler import WorkspaceContextCompiler


@pytest.mark.asyncio
async def test_unclassified_legacy_conversation_turn_is_local_only_but_note_uses_profile(test_db_session):
    legacy_turn = WorkspaceObjectModel(
        id="legacy-conversation-turn",
        project_name="Atlas",
        object_type="conversation_turn",
        title="Old assistant response",
        content="A prior answer that may contain private context.",
        metadata_json={"role": "assistant", "run_id": "legacy-run"},
        created_by="assistant",
    )
    unclassified_note = WorkspaceObjectModel(
        id="unclassified-manual-note",
        project_name="Atlas",
        object_type="manual_note",
        title="Project note",
        content="An ordinary project note.",
        metadata_json={},
        created_by="user",
    )
    test_db_session.add_all([legacy_turn, unclassified_note])
    await test_db_session.commit()

    compiler = WorkspaceContextCompiler(test_db_session)
    compiled_turn = await compiler.compile("Atlas", [legacy_turn.id])
    compiled_note = await compiler.compile("Atlas", [unclassified_note.id])

    assert compiled_turn.privacy_requirement == "local_only"
    assert compiled_turn.privacy_sources == [{
        "object_id": legacy_turn.id,
        "privacy_policy": "local_only",
    }]
    assert compiled_note.privacy_requirement is None
    assert compiled_note.privacy_sources == []
