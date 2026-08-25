from visit_report_ai.core.config import Settings
from visit_report_ai.schemas.forms import ExtractRequest, FieldSuggestion, FormDefinition, FormFieldDefinition
from visit_report_ai.services.extraction import ExtractionService


def test_dynamic_form_only_requires_declared_required_fields() -> None:
    service = ExtractionService(Settings())
    request = ExtractRequest(
        transcript="在客户会议室进行了交流。",
        form=FormDefinition(
            fields=[
                FormFieldDefinition(key="location", label="互动地点", required=True),
                FormFieldDefinition(key="description", label="说明", required=True),
                FormFieldDefinition(key="need", label="客户需求"),
            ]
        ),
    )
    fields = service._parse_fields(
        request.form.fields,
        {"fields": {"location": "客户会议室"}},
    )
    missing, _ = service._validate(request, fields)
    assert [item.field for item in missing] == ["description"]


def test_value_outside_dynamic_options_is_discarded() -> None:
    service = ExtractionService(Settings())
    definitions = [FormFieldDefinition(key="contact_level", label="联系人层级", options=["高管理", "中管层", "一般管理"])]
    fields = service._parse_fields(
        definitions,
        {"fields": {"contact_level": "董事长"}},
    )
    assert fields["contact_level"] is None


def test_metadata_is_only_parsed_when_requested() -> None:
    service = ExtractionService(Settings())
    definitions = [FormFieldDefinition(key="location", label="互动地点")]
    payload = {"fields": {"location": {"value": "客户会议室", "confidence": 0.9, "evidence": "客户会议室"}}}

    lightweight = service._parse_fields(definitions, {"fields": {"location": "客户会议室"}})
    detailed = service._parse_fields(definitions, payload, include_metadata=True)

    assert lightweight == {"location": "客户会议室"}
    assert isinstance(detailed["location"], FieldSuggestion)
    assert detailed["location"].evidence == "客户会议室"


def test_null_metadata_confidence_defaults_to_zero() -> None:
    service = ExtractionService(Settings())
    definitions = [FormFieldDefinition(key="location", label="互动地点")]
    fields = service._parse_fields(
        definitions,
        {"fields": {"location": {"value": "客户会议室", "confidence": None, "evidence": "客户会议室"}}},
        include_metadata=True,
    )

    assert fields["location"].confidence == 0


def test_dynamic_form_ignores_undeclared_fields_and_reports_low_confidence() -> None:
    service = ExtractionService(Settings())
    request = ExtractRequest(
        transcript="客户正在比较供应商。",
        form=FormDefinition(fields=[FormFieldDefinition(key="risk", label="丢单风险")]),
    )
    fields = service._parse_fields(
        request.form.fields,
        {"fields": {"risk": {"value": "价格偏高", "confidence": 0.6, "evidence": "比较供应商"}, "extra": {}}},
        include_metadata=True,
    )
    _, warnings = service._validate(request, fields)
    assert list(fields) == ["risk"]
    assert [item.field for item in warnings] == ["risk"]


def test_dynamic_form_rejects_duplicate_keys() -> None:
    try:
        FormDefinition(
            fields=[
                FormFieldDefinition(key="location", label="地点"),
                FormFieldDefinition(key="location", label="客户地点"),
            ]
        )
    except ValueError as error:
        assert "unique keys" in str(error)
    else:
        raise AssertionError("duplicate field keys must be rejected")


def test_completion_parser_accepts_json_code_block() -> None:
    payload = ExtractionService._parse_completion_content('```json\n{"fields": {"location": "客户会议室"}}\n```')

    assert payload == {"fields": {"location": "客户会议室"}}


def test_completion_parser_accepts_text_around_json() -> None:
    payload = ExtractionService._parse_completion_content(
        '以下是识别结果：{"fields": {"location": "客户会议室"}}以上。'
    )

    assert payload == {"fields": {"location": "客户会议室"}}


def test_completion_parser_rejects_empty_content() -> None:
    try:
        ExtractionService._parse_completion_content("", {"finish_reason": "length", "message": {"reasoning_content": "思考"}})
    except ValueError as error:
        assert str(error) == "LLM returned empty completion content (model=None, finish_reason=length, reasoning_content_length=2)"
    else:
        raise AssertionError("empty completion content must be rejected")


def test_completion_parser_rejects_non_json_content() -> None:
    try:
        ExtractionService._parse_completion_content("无法识别")
    except ValueError as error:
        assert str(error) == "LLM completion content is not valid JSON"
    else:
        raise AssertionError("non-JSON completion content must be rejected")
