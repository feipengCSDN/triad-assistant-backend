import json

import httpx

from visit_report_ai.core.config import Settings
from visit_report_ai.schemas.forms import (
    ExtractRequest,
    ExtractResponse,
    FieldSuggestion,
    FormFieldDefinition,
    ValidationIssue,
)


class ExtractionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract(self, request: ExtractRequest) -> ExtractResponse:
        payload = await self._request_completion(request)
        fields = self._parse_fields(request.form.fields, payload)
        missing, warnings = self._validate(request, fields)
        return ExtractResponse(
            transcript=request.transcript,
            fields=fields,
            missing_required_fields=missing,
            warnings=warnings,
        )

    async def _request_completion(self, request: ExtractRequest) -> dict:
        if not self.settings.llm_base_url or not self.settings.llm_api_key or not self.settings.llm_model:
            raise RuntimeError("LLM service is not configured")
        field_definitions = [field.model_dump() for field in request.form.fields]
        prompt = (
            "从中文语音转写中提取表单信息。不得编造；原文未明确提及的 value 必须为 null，confidence 为 0。"
            "每个字段的 evidence 必须是原文中的短证据或 null。"
            f"字段定义：{json.dumps(field_definitions, ensure_ascii=False)}。"
            "仅提取字段定义中给出的 key。若字段包含 options，value 必须为其中一个选项或 null。"
            "只输出 JSON，对象格式为 {\"fields\": {字段英文名: {\"value\": string|null, \"confidence\": 0到1, \"evidence\": string|null}}}。"
            f"转写原文：{request.transcript}"
        )
        body = {
            "model": self.settings.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You extract only supported form fields and return valid JSON."},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
            )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def _parse_fields(self, definitions: list[FormFieldDefinition], payload: dict) -> dict[str, FieldSuggestion]:
        raw_fields = payload.get("fields")
        if not isinstance(raw_fields, dict):
            raise ValueError("LLM response does not contain fields object")
        fields: dict[str, FieldSuggestion] = {}
        for definition in definitions:
            raw_value = raw_fields.get(definition.key)
            suggestion = FieldSuggestion.model_validate(raw_value) if isinstance(raw_value, dict) else FieldSuggestion()
            if definition.options and suggestion.value not in definition.options:
                suggestion = FieldSuggestion(value=None, confidence=0, evidence=suggestion.evidence)
            fields[definition.key] = suggestion
        return fields

    def _validate(
        self,
        request: ExtractRequest,
        fields: dict[str, FieldSuggestion],
    ) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
        missing: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        for definition in request.form.fields:
            if definition.required and not fields[definition.key].value:
                missing.append(ValidationIssue(field=definition.key, message="该字段为必填项，转写内容未提供明确值"))
        for field_name, suggestion in fields.items():
            if suggestion.value and suggestion.confidence < 0.7:
                warnings.append(ValidationIssue(field=field_name, message="识别置信度低于 0.7，请人工确认"))
        return missing, warnings
