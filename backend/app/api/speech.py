import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.speech.stt_service import (
    STTError,
    STTUnavailableError,
    create_stt_service,
    get_stt_mode,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/speech", tags=["speech"])

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".ogg", ".webm"}
UPLOAD_CHUNK_SIZE = 1024 * 1024


class TranscriptionResponse(BaseModel):
    transcript: str
    language: str = "en"
    status: str = "ok"


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
) -> TranscriptionResponse:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    mode = get_stt_mode()
    logger.info(
        "Speech transcription endpoint called: filename=%r mode=%s",
        filename,
        mode,
    )

    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        logger.warning("Unsupported audio file: filename=%r", filename)
        raise HTTPException(
            status_code=415,
            detail="Unsupported audio file type. Use .wav, .ogg, or .webm.",
        )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=suffix,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            bytes_written = 0
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                temporary_file.write(chunk)
                bytes_written += len(chunk)

        if bytes_written == 0:
            logger.warning("Empty audio upload: filename=%r", filename)
            raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

        service = create_stt_service()
        transcript = (
            await run_in_threadpool(service.transcribe, temporary_path)
        ).strip()
        if not transcript:
            raise STTError("Speech transcription returned an empty transcript.")

        logger.info(
            "Speech transcription completed: mode=%s transcript_length=%d",
            mode,
            len(transcript),
        )
        return TranscriptionResponse(transcript=transcript)
    except HTTPException:
        raise
    except STTUnavailableError as exc:
        logger.error("Speech transcription unavailable: mode=%s error=%s", mode, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except STTError as exc:
        logger.error("Speech transcription failed: mode=%s error=%s", mode, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected speech transcription error: mode=%s", mode)
        raise HTTPException(
            status_code=500,
            detail="Unexpected speech transcription error.",
        ) from exc
    finally:
        await file.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
