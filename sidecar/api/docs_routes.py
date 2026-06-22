"""Routes for Document Generation (#5) and multimodal OCR/transcription."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import tools
from ..docs import generator
from ..multimodal import extract
from ..storage.db import Database


class GenerateDoc(BaseModel):
    project_id: int
    format: str = "md"          # md | docx | pdf
    style: str = "apa"          # ieee | acm | apa
    title: str | None = None
    author: str = "Phorrom"


class OcrRequest(BaseModel):
    path: str
    lang: str = "eng"


class TranscribeRequest(BaseModel):
    path: str
    model: str | None = None


def build_docs_router() -> APIRouter:
    router = APIRouter()

    @router.get("/tools/status")
    async def tools_status() -> dict:
        return tools.status()

    @router.post("/docs/generate")
    async def generate_doc(body: GenerateDoc, request: Request) -> dict:
        db: Database = request.app.state.db
        try:
            return generator.generate(db, body.project_id, body.format, body.style,
                                       body.title, body.author)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @router.post("/multimodal/ocr")
    async def ocr(body: OcrRequest) -> dict:
        return extract.ocr_image(body.path, body.lang)

    @router.post("/multimodal/transcribe")
    async def transcribe(body: TranscribeRequest) -> dict:
        return extract.transcribe_audio(body.path, body.model)

    return router
