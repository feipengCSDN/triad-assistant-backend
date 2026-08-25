import logging

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from visit_report_ai.core.config import get_settings
from visit_report_ai.schemas.forms import (
    ExtractRequest,
    ExtractResponse,
    TranscribeResponse,
)
from visit_report_ai.services.asr import AsrService
from visit_report_ai.services.extraction import ExtractionService

settings = get_settings()
logging.basicConfig(level=settings.log_level)
app = FastAPI(title="拜访互动 AI 填报服务", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


def raise_service_error(error: Exception) -> None:
    if isinstance(error, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if isinstance(error, RuntimeError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    logging.exception("AI service request failed")
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI upstream service is unavailable") from error


async def read_audio(audio: UploadFile) -> bytes:
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only audio uploads are supported")
    content = await audio.read(settings.max_audio_bytes + 1)
    if len(content) > settings.max_audio_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio file exceeds configured size limit")
    return content


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{settings.api_prefix}/form-extractions", response_model=ExtractResponse)
async def extract_from_transcript(request: ExtractRequest) -> ExtractResponse:
    try:
        return await ExtractionService(settings).extract(request)
    except Exception as error:
        raise_service_error(error)


@app.post(f"{settings.api_prefix}/transcriptions", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(...)) -> TranscribeResponse:
    try:
        content = await read_audio(audio)
        text = await AsrService(settings).transcribe(content, audio.filename or "audio", audio.content_type)
        return TranscribeResponse(transcript=text)
    except HTTPException:
        raise
    except Exception as error:
        raise_service_error(error)


@app.post(f"{settings.api_prefix}/voice-form-extractions", response_model=TranscribeResponse)
async def extract_from_voice(audio: UploadFile = File(...)) -> TranscribeResponse:
    try:
        content = await read_audio(audio)
        text = await AsrService(settings).transcribe(content, audio.filename or "audio", audio.content_type)
        return TranscribeResponse(transcript=text)
    except HTTPException:
        raise
    except Exception as error:
        raise_service_error(error)
