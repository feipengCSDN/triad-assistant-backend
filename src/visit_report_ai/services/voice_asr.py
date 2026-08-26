import logging
import time

import httpx

from visit_report_ai.core.config import Settings

logger = logging.getLogger(__name__)


class VoiceAsrService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def transcribe(self, content: bytes, filename: str, content_type: str) -> str:
        if not self.settings.voice_asr_base_url:
            raise RuntimeError("Voice ASR service is not configured")
        if content[:4] != b"RIFF" or content[8:12] != b"WAVE":
            raise ValueError("Voice ASR only supports WAV audio")
        files = {"file": (filename or "audio.wav", content, content_type)}
        upstream_url = f"{self.settings.voice_asr_base_url.rstrip('/')}/v1/asr/transcribe"
        logger.info(
            "voice asr forwarding url=%s filename=%s content_type=%s bytes=%d language=zh",
            upstream_url,
            filename,
            content_type,
            len(content),
        )
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            response = await client.post(
                upstream_url,
                data={"language": "zh"},
                files=files,
            )
        logger.info(
            "voice asr upstream response url=%s status=%d elapsed_ms=%.0f response_bytes=%d",
            upstream_url,
            response.status_code,
            (time.perf_counter() - started_at) * 1000,
            len(response.content),
        )
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:500]
            raise RuntimeError(f"Voice ASR upstream returned HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError("Voice ASR upstream returned invalid JSON") from error
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Voice ASR response did not include transcript text")
        return text.strip()
