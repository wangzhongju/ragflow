"""Canonical training samples and immutable generation settings."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .source import FactoryError


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_mode: Literal["existing", "template", "llm"] = "existing"
    model_id: str = ""
    prompt: str = Field(default="根据证据生成真实用户会提出的问题，问题应具体且能由证据回答。", max_length=2000)
    questions_per_chunk: int = Field(default=1, ge=1, le=5)
    max_samples: int = Field(default=20, ge=1, le=5000)
    max_calls: int = Field(default=5, ge=0, le=100)
    token_budget: int = Field(default=8000, ge=0, le=200000)
    output_tokens: int = Field(default=256, ge=64, le=2048)
    retrieval: Literal["lexical", "vector", "hybrid"] = "lexical"
    retrieval_scope: Literal["documents", "snapshot"] = "snapshot"
    vector_weight: float = Field(default=0.5, ge=0, le=1)
    threshold: float = Field(default=0.2, ge=0, le=1)
    candidate_count: int = Field(default=12, ge=2, le=100)
    knn_top_k: int = Field(default=32, ge=2, le=1024)
    knn_candidates: int = Field(default=64, ge=2, le=4096)
    rerank_id: str = ""
    positive_count: int = Field(default=3, ge=1, le=20)
    negative_count: int = Field(default=3, ge=1, le=20)
    hard_ratio: float = Field(default=1.0, ge=0, le=1)
    negative_relevance_ceiling: float = Field(default=0.8, ge=0, le=1)
    near_duplicate_threshold: float = Field(default=0.85, ge=0.5, le=1)
    modalities: list[Literal["text", "image", "audio", "video", "structured"]] = ["text"]
    train_percent: int = Field(default=80, ge=1, le=98)
    validation_percent: int = Field(default=10, ge=1, le=98)
    seed: int = Field(default=42, ge=0, le=2147483647)

    def checked(self):
        if self.train_percent + self.validation_percent >= 100:
            raise FactoryError("训练集和验证集比例之和必须小于 100")
        if self.knn_candidates < self.knn_top_k:
            raise FactoryError("候选池不能小于 Top K")
        if self.query_mode == "llm" and not self.model_id:
            raise FactoryError("LLM 生成需要选择模型")
        return self


def settings(value):
    try:
        return Settings.model_validate(value or {}).checked().model_dump()
    except ValidationError as exc:
        raise FactoryError("配置无效：" + str(exc.errors(include_url=False)[0]["msg"])) from exc


class TextPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text"]
    text: str = Field(min_length=1)
    asset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class StructuredPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["structured"]
    value: dict | list


class MediaPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image", "audio", "video"]
    asset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    page: int | None = Field(default=None, ge=1)
    region: list[float] | None = None
    time_ms: list[int] | None = None


ContentPart = Annotated[TextPart | StructuredPart | MediaPart, Field(discriminator="type")]


class Negative(BaseModel):
    model_config = ConfigDict(extra="allow")
    evidence_id: str
    method: str


class Candidate(Negative):
    label: Literal[0, 1, 2] | None


class EmbeddingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: list[ContentPart]
    positives: list[str]
    negatives: list[Negative]


class RerankerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: list[ContentPart]
    candidates: list[Candidate]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart]


class LLMPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[Message] = Field(min_length=1)
    evidence_ids: list[str]
    supervised_turns: list[int]


class Sample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2] = 2
    sample_id: str
    revision: int = Field(ge=1)
    task: Literal["embedding", "reranker", "llm"]
    snapshot_id: str
    group_id: str
    split: Literal["train", "validation", "test"]
    evidence_ids: list[str]
    provenance: dict
    payload: dict

    @model_validator(mode="after")
    def validate_payload(self):
        model = {"embedding": EmbeddingPayload, "reranker": RerankerPayload, "llm": LLMPayload}[self.task]
        model.model_validate(self.payload)
        return self


def parts_valid(parts):
    from pydantic import TypeAdapter

    try:
        parsed = TypeAdapter(list[ContentPart]).validate_python(parts)
        if not parsed:
            raise FactoryError("内容不能为空")
        for part in parsed:
            if isinstance(part, MediaPart):
                if part.region is not None and (len(part.region) != 4 or not all(0 <= n <= 1 for n in part.region) or part.region[0] >= part.region[2] or part.region[1] >= part.region[3]):
                    raise FactoryError("区域必须为归一化 xyxy")
                if part.time_ms is not None and (len(part.time_ms) != 2 or not 0 <= part.time_ms[0] < part.time_ms[1]):
                    raise FactoryError("时间区间必须为有效毫秒区间")
        return parts
    except ValidationError as exc:
        raise FactoryError("ContentPart 结构无效") from exc


def query_text(sample):
    parts = sample["payload"].get("query", [])
    if sample["task"] == "llm":
        parts = next((m["content"] for m in sample["payload"]["messages"] if m["role"] == "user"), [])
    return " ".join(p.get("text", "") for p in parts).strip()


def evidence_refs(sample):
    payload = sample["payload"]
    if sample["task"] == "embedding":
        return payload["positives"] + [n["evidence_id"] for n in payload["negatives"]]
    if sample["task"] == "reranker":
        return [c["evidence_id"] for c in payload["candidates"]]
    return payload["evidence_ids"]
