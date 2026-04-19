from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI()

DATA_DIR = Path(__file__).resolve().parent / "data"
MEMORY_FILE = DATA_DIR / "memories.json"
MEMORY_LOCK = threading.Lock()


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    source: str = Field(default="manual")


class MemoryRecord(MemoryCreate):
    id: str
    timestamp: str


class MemoryQueryResult(BaseModel):
    count: int
    results: list[MemoryRecord]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text("[]", encoding="utf-8")


def _load_memories() -> list[dict[str, Any]]:
    _ensure_storage()
    raw_text = MEMORY_FILE.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Memory store is corrupted") from exc

    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="Memory store has an invalid format")

    return data


def _save_memories(memories: list[dict[str, Any]]) -> None:
    _ensure_storage()
    temporary_path = MEMORY_FILE.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(memories, indent=2, ensure_ascii=True), encoding="utf-8")
    temporary_path.replace(MEMORY_FILE)


def _to_record(memory: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(**memory)


def _dump_record(record: MemoryRecord) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        return record.model_dump()
    return record.dict()


def _matches(memory: MemoryRecord, query: str | None, tag: str | None, source: str | None) -> bool:
    if query and query.lower() not in memory.content.lower():
        return False

    if tag and tag not in memory.tags:
        return False

    if source and source.lower() != memory.source.lower():
        return False

    return True


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "message": "DACMI memory service is running",
        "storage": str(MEMORY_FILE),
    }


@app.post("/store", response_model=MemoryRecord)
async def store(memory: MemoryCreate):
    record = MemoryRecord(
        id=str(uuid.uuid4()),
        content=memory.content.strip(),
        tags=[tag.strip() for tag in memory.tags if tag.strip()],
        source=memory.source.strip() or "manual",
        timestamp=_now_iso(),
    )

    with MEMORY_LOCK:
        memories = _load_memories()
        memories.append(_dump_record(record))
        _save_memories(memories)

    return record


@app.get("/query", response_model=MemoryQueryResult)
async def query(
    q: str | None = Query(default=None, description="Search text inside memory content"),
    tag: str | None = Query(default=None, description="Filter by tag"),
    source: str | None = Query(default=None, description="Filter by source"),
):
    with MEMORY_LOCK:
        memories = [_to_record(memory) for memory in _load_memories()]

    results = [memory for memory in memories if _matches(memory, q, tag, source)]
    return MemoryQueryResult(count=len(results), results=results)