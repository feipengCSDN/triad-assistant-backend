from pydantic import BaseModel, Field, model_validator


class FieldSuggestion(BaseModel):
    value: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    evidence: str | None = None


class FormFieldDefinition(BaseModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=50)


class FormDefinition(BaseModel):
    fields: list[FormFieldDefinition] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_unique_field_keys(self) -> "FormDefinition":
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("form fields must have unique keys")
        return self


class ExtractRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=20_000)
    form: FormDefinition


class ValidationIssue(BaseModel):
    field: str
    message: str


class ExtractResponse(BaseModel):
    transcript: str
    fields: dict[str, FieldSuggestion]
    missing_required_fields: list[ValidationIssue]
    warnings: list[ValidationIssue]


class TranscribeResponse(BaseModel):
    transcript: str
