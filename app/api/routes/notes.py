"""Durable user-authored Notes for the personal AURA workspace."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PersonalNoteCreate, PersonalNoteResponse, PersonalNoteUpdate
from app.db.models import PersonalNoteModel
from app.db.session import get_db

router = APIRouter(prefix="/v1/notes", tags=["Notes"])


def _response(note: PersonalNoteModel) -> PersonalNoteResponse:
    return PersonalNoteResponse(
        id=note.id,
        title=note.title,
        body=note.body,
        tags=note.tags_json or [],
        project_ids=note.project_ids_json or [],
        project_names=note.project_names_json or [],
        pinned=note.pinned,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.get("", response_model=list[PersonalNoteResponse])
async def list_personal_notes(db: AsyncSession = Depends(get_db)) -> list[PersonalNoteResponse]:
    result = await db.execute(
        select(PersonalNoteModel).order_by(
            PersonalNoteModel.pinned.desc(),
            PersonalNoteModel.updated_at.desc(),
            PersonalNoteModel.id,
        )
    )
    return [_response(note) for note in result.scalars()]


@router.post("", response_model=PersonalNoteResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_note(
    body: PersonalNoteCreate,
    db: AsyncSession = Depends(get_db),
) -> PersonalNoteResponse:
    note = await db.get(PersonalNoteModel, body.id) if body.id else None
    if note is None:
        note = PersonalNoteModel(id=body.id) if body.id else PersonalNoteModel()
        db.add(note)

    note.title = body.title
    note.body = body.body
    note.tags_json = list(dict.fromkeys(tag.strip() for tag in body.tags if tag.strip()))
    note.project_ids_json = list(dict.fromkeys(body.project_ids))
    note.project_names_json = list(dict.fromkeys(name.strip() for name in body.project_names if name.strip()))
    note.pinned = body.pinned
    note.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(note)
    return _response(note)


@router.put("/{note_id}", response_model=PersonalNoteResponse)
async def update_personal_note(
    note_id: str,
    body: PersonalNoteUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonalNoteResponse:
    note = await db.get(PersonalNoteModel, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Personal note not found.")
    note.title = body.title
    note.body = body.body
    note.tags_json = list(dict.fromkeys(tag.strip() for tag in body.tags if tag.strip()))
    note.project_ids_json = list(dict.fromkeys(body.project_ids))
    note.project_names_json = list(dict.fromkeys(name.strip() for name in body.project_names if name.strip()))
    note.pinned = body.pinned
    note.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(note)
    return _response(note)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_note(note_id: str, db: AsyncSession = Depends(get_db)) -> None:
    note = await db.get(PersonalNoteModel, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Personal note not found.")
    await db.delete(note)
    await db.commit()
