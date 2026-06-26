from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.speech.tts_service import tts_debug_enabled


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tts", tags=["tts"])


@router.get("/audio/{audio_id}")
async def get_tts_audio(audio_id: str, request: Request) -> Response:
    if tts_debug_enabled():
        logger.info("tts_audio_get audio_id=%s", audio_id)
    store = request.app.state.tts_audio_store
    entry = store.pop(audio_id)
    if entry is None:
        logger.warning("tts_audio_missing audio_id=%s", audio_id)
        raise HTTPException(
            status_code=404,
            detail={
                "code": "tts_audio_not_found",
                "message": "NPC voice audio was not found or has expired.",
            },
        )
    if tts_debug_enabled():
        logger.info(
            "tts_audio_returned audio_id=%s bytes=%d",
            audio_id,
            len(entry.audio_bytes),
        )
    return Response(
        content=entry.audio_bytes,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "X-KotoDama-Audio-Duration-Ms": str(entry.duration_ms),
        },
    )
