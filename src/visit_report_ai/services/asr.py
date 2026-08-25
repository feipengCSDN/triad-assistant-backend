import httpx

from visit_report_ai.core.config import Settings


class AsrService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def transcribe(self, content: bytes, filename: str, content_type: str) -> str:
        if not self.settings.asr_base_url or not self.settings.asr_api_key:
            raise RuntimeError("ASR service is not configured")
        if content[:4] == b"RIFF" and content[8:12] == b"WAVE":
            filename = "audio.wav"
            content_type = "audio/wav"
        elif not content[:3] == b"ID3" and not content[:2] == b"\xff\xfb":
            raise RuntimeError(
                f"Unsupported audio format: filename={filename}, content_type={content_type}; "
                "please upload WAV or MP3"
            )
        headers = {"Authorization": f"Bearer {self.settings.asr_api_key}"}
        files = {"file": (filename, content, content_type)}
        data = {"model": self.settings.asr_model, "stream": "false"}
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.asr_base_url.rstrip('/')}/audio/transcriptions",
                headers=headers,
                data=data,
                files=files,
            )
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:500]
            raise RuntimeError(f"ASR upstream returned HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError("ASR upstream returned invalid JSON") from error
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("ASR response did not include transcript text")
        return text.strip()
