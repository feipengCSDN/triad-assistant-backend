from fastapi.testclient import TestClient

from visit_report_ai.main import app
from visit_report_ai.schemas.forms import ExtractResponse, FieldSuggestion
from visit_report_ai.services.asr import AsrService
from visit_report_ai.services.extraction import ExtractionService


def test_voice_form_extractions_only_transcribes(monkeypatch) -> None:
    async def transcribe(self, content: bytes, filename: str, content_type: str) -> str:
        return "客户会议室沟通设备交付计划。"

    async def extract(self, request):
        raise AssertionError("voice-form-extractions must not extract form fields")

    monkeypatch.setattr(AsrService, "transcribe", transcribe)
    monkeypatch.setattr(ExtractionService, "extract", extract)

    response = TestClient(app).post(
        "/api/v1/voice-form-extractions",
        files={"audio": ("visit.wav", b"audio", "audio/wav")},
        data={"scenario": "visit_interaction", "task_type": "商机跟进"},
    )

    assert response.status_code == 200
    assert response.json() == {"transcript": "客户会议室沟通设备交付计划。"}


def test_voice_form_extractions_does_not_require_form_parameters(monkeypatch) -> None:
    async def transcribe(self, content: bytes, filename: str, content_type: str) -> str:
        return "转写结果"

    monkeypatch.setattr(AsrService, "transcribe", transcribe)

    response = TestClient(app).post(
        "/api/v1/voice-form-extractions",
        files={"audio": ("visit.wav", b"audio", "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {"transcript": "转写结果"}


def test_form_extractions_uses_client_form_definition(monkeypatch) -> None:
    async def extract(self, request):
        assert request.transcript == "客户在总部会议室沟通交付计划。"
        assert [field.key for field in request.form.fields] == ["location", "next_step"]
        return ExtractResponse(
            transcript=request.transcript,
            fields={
                "location": FieldSuggestion(value="客户总部会议室", confidence=0.9, evidence="客户在总部会议室"),
                "next_step": FieldSuggestion(),
            },
            missing_required_fields=[],
            warnings=[],
        )

    monkeypatch.setattr(ExtractionService, "extract", extract)

    response = TestClient(app).post(
        "/api/v1/form-extractions",
        json={
            "transcript": "客户在总部会议室沟通交付计划。",
            "include_metadata": True,
            "form": {
                "fields": [
                    {"key": "location", "label": "互动地点", "required": True},
                    {"key": "next_step", "label": "下一步行动"},
                ]
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["fields"]["location"]["value"] == "客户总部会议室"
    assert "next_step" not in response.json()["fields"]


def test_form_extractions_rejects_duplicate_field_keys() -> None:
    response = TestClient(app).post(
        "/api/v1/form-extractions",
        json={
            "transcript": "客户会议室沟通。",
            "form": {
                "fields": [
                    {"key": "location", "label": "互动地点"},
                    {"key": "location", "label": "客户地点"},
                ]
            },
        },
    )

    assert response.status_code == 422
