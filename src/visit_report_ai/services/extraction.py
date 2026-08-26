import json
import logging
import time

import httpx

from visit_report_ai.core.config import Settings
from visit_report_ai.schemas.forms import (
    ExtractRequest,
    ExtractResponse,
    FieldSuggestion,
    FormFieldDefinition,
    ValidationIssue,
)

logger = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract(self, request: ExtractRequest) -> ExtractResponse:
        started_at = time.perf_counter()
        logger.info(
            "form extraction started fields=%d transcript_chars=%d include_metadata=%s model=%s",
            len(request.form.fields),
            len(request.transcript),
            request.include_metadata,
            self.settings.llm_model,
        )
        payload = await self._request_completion(request)
        fields = self._parse_fields(request.form.fields, payload, request.include_metadata)
        missing, warnings = self._validate(request, fields)
        response_fields = {
            key: value
            for key, value in fields.items()
            if (value.value if isinstance(value, FieldSuggestion) else value) is not None
        }
        logger.info(
            "form extraction completed elapsed_ms=%.0f fields=%d missing=%d warnings=%d",
            (time.perf_counter() - started_at) * 1000,
            len(response_fields),
            len(missing),
            len(warnings),
        )
        return ExtractResponse(
            transcript=request.transcript,
            fields=response_fields,
            missing_required_fields=missing,
            warnings=warnings,
        )

    async def _request_completion(self, request: ExtractRequest) -> dict:
        if not self.settings.llm_base_url or not self.settings.llm_api_key or not self.settings.llm_model:
            raise RuntimeError("LLM service is not configured")
        field_definitions = [
            {key: value for key, value in {"key": field.key, "label": field.label, "options": field.options}.items() if value}
            for field in request.form.fields
        ]
        output_format = (
            '{"fields": {字段英文名: string|null}}'
            if not request.include_metadata
            else '{"fields": {字段英文名: {"value": string|null, "confidence": 0到1, "evidence": string|null}}}'
        )
        prompt = (
            "从中文语音转写中提取表单信息。不得编造；原文未明确提及的字段 value 必须为 null。"
            "启用元数据时，confidence 始终必须是 0 到 1 的数字；未识别时必须为 0，不能为 null。"
            f"字段定义：{json.dumps(field_definitions, ensure_ascii=False)}。"
            "仅提取字段定义中给出的 key。若字段包含 options，value 必须为其中一个选项或 null。"
            f"只输出 JSON，对象格式为 {output_format}。"
            f"转写原文：{request.transcript}"
        )
        body = {
            "model": self.settings.llm_model,
            "temperature": 0,
            "max_tokens": self.settings.llm_metadata_max_tokens if request.include_metadata else self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You extract only supported form fields and return valid JSON."},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        upstream_started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
            )
        logger.info(
            "llm completion received elapsed_ms=%.0f status=%d response_bytes=%d",
            (time.perf_counter() - upstream_started_at) * 1000,
            response.status_code,
            len(response.content),
        )
        response.raise_for_status()
        try:
            response_payload = response.json()
        except json.JSONDecodeError as error:
            raise ValueError("LLM upstream returned an empty or non-JSON HTTP response") from error
        try:
            choice = response_payload["choices"][0]
            content = choice["message"]["content"]
        except (IndexError, KeyError, TypeError) as error:
            logger.warning("llm response shape invalid top_level_keys=%s", list(response_payload)[:10])
            raise ValueError("LLM upstream response does not contain choices[0].message.content") from error
        logger.info(
            "llm completion parsed content_type=%s content_chars=%d finish_reason=%s usage=%s",
            type(content).__name__,
            len(content) if isinstance(content, str) else 0,
            choice.get("finish_reason"),
            response_payload.get("usage"),
        )
        return self._parse_completion_content(content, choice)

    @staticmethod
    def _parse_completion_content(content: object, choice: dict | None = None) -> dict:
        if not isinstance(content, str) or not content.strip():
            finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
            message = choice.get("message") if isinstance(choice, dict) else None
            reasoning_content = message.get("reasoning_content") if isinstance(message, dict) else None
            reasoning_length = len(reasoning_content) if isinstance(reasoning_content, str) else 0
            raise ValueError(
                "LLM returned empty completion content "
                f"(model={choice.get('model') if isinstance(choice, dict) else None}, "
                f"finish_reason={finish_reason}, reasoning_content_length={reasoning_length})"
            )
        normalized = content.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if len(lines) >= 3 and lines[-1].strip().startswith("```"):
                normalized = "\n".join(lines[1:-1]).strip()
        if not normalized.startswith("{"):
            object_start = normalized.find("{")
            if object_start >= 0:
                normalized = normalized[object_start:]
        try:
            payload, _ = json.JSONDecoder().raw_decode(normalized)
        except json.JSONDecodeError as error:
            logger.warning(
                "llm completion json invalid content_chars=%d error_position=%d error=%s preview=%r finish_reason=%s",
                len(normalized),
                error.pos,
                error.msg,
                normalized[:160],
                choice.get("finish_reason") if isinstance(choice, dict) else None,
            )
            raise ValueError("LLM completion content is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("LLM completion JSON must be an object")
        return payload

    def _parse_fields(
        self,
        definitions: list[FormFieldDefinition],
        payload: dict,
        include_metadata: bool = False,
    ) -> dict[str, str | None | FieldSuggestion]:
        raw_fields = payload.get("fields")
        if not isinstance(raw_fields, dict):
            raise ValueError("LLM response does not contain fields object")
        fields: dict[str, str | None | FieldSuggestion] = {}
        for definition in definitions:
            raw_value = raw_fields.get(definition.key)
            if include_metadata:
                if isinstance(raw_value, dict) and raw_value.get("confidence") is None:
                    raw_value = {**raw_value, "confidence": 0}
                suggestion = FieldSuggestion.model_validate(raw_value) if isinstance(raw_value, dict) else FieldSuggestion()
                if definition.options and suggestion.value not in definition.options:
                    suggestion = FieldSuggestion(value=None, confidence=0, evidence=suggestion.evidence)
                fields[definition.key] = suggestion
            else:
                value = raw_value if isinstance(raw_value, str) else None
                fields[definition.key] = value if not definition.options or value in definition.options else None
        return fields

    def _validate(
        self,
        request: ExtractRequest,
        fields: dict[str, str | None | FieldSuggestion],
    ) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
        missing: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        for definition in request.form.fields:
            field = fields[definition.key]
            value = field.value if isinstance(field, FieldSuggestion) else field
            if definition.required and not value:
                missing.append(ValidationIssue(field=definition.key, message="该字段为必填项，转写内容未提供明确值"))
        for field_name, suggestion in fields.items():
            if isinstance(suggestion, FieldSuggestion) and suggestion.value and suggestion.confidence < 0.7:
                warnings.append(ValidationIssue(field=field_name, message="识别置信度低于 0.7，请人工确认"))
        return missing, warnings
