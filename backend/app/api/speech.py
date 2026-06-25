import logging
import tempfile
from pathlib import Path
from time import perf_counter

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.speech.stt_service import (
    STTError,
    STTAudioTooShortError,
    STTMalformedAudioError,
    STTNoSpeechError,
    STTUnavailableError,
    create_stt_service,
    get_stt_mode,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/speech", tags=["speech"])

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".ogg", ".webm"}
UPLOAD_CHUNK_SIZE = 1024 * 1024


class TranscriptionMetadata(BaseModel):
    model: str
    audio_duration_ms: int | None = None
    transcription_ms: int
    speech_detected: bool
    mode: str


class TranscriptionResponse(BaseModel):
    transcript: str
    language: str = "en"
    status: str = "ok"
    metadata: TranscriptionMetadata | None = None


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
) -> TranscriptionResponse:
    filename = file.filename or ""
    request_started_at = perf_counter()
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
            raise _speech_error(400, "no_audio", "Uploaded audio file is empty.")

        service = create_stt_service()
        result = await run_in_threadpool(service.transcribe_detailed, temporary_path)

        logger.info(
            "stt_utterance transport=http mode=%s model=%s audio_ms=%s "
            "transcription_ms=%d delivery_ms=%.1f speech_detected=%s",
            result.mode,
            result.model,
            result.audio_duration_ms,
            result.transcription_ms,
            (perf_counter() - request_started_at) * 1000,
            result.speech_detected,
        )
        return TranscriptionResponse(
            transcript=result.transcript,
            language=result.language,
            metadata=TranscriptionMetadata(
                model=result.model,
                audio_duration_ms=result.audio_duration_ms,
                transcription_ms=result.transcription_ms,
                speech_detected=result.speech_detected,
                mode=result.mode,
            ),
        )
    except HTTPException:
        raise
    except STTUnavailableError as exc:
        logger.error("Speech transcription unavailable: mode=%s error=%s", mode, exc)
        raise _speech_error(503, exc.code, str(exc)) from exc
    except STTNoSpeechError as exc:
        logger.info("Speech transcription found no speech: mode=%s", mode)
        raise _speech_error(422, exc.code, str(exc)) from exc
    except STTAudioTooShortError as exc:
        logger.info("Speech recording too short: mode=%s", mode)
        raise _speech_error(422, exc.code, str(exc)) from exc
    except STTMalformedAudioError as exc:
        logger.warning("Malformed audio upload: filename=%r", filename)
        raise _speech_error(400, exc.code, str(exc)) from exc
    except STTError as exc:
        logger.error("Speech transcription failed: mode=%s error=%s", mode, exc)
        raise _speech_error(500, exc.code, str(exc)) from exc
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


def _speech_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})
