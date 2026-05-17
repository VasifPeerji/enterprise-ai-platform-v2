"""
📁 File: src/layer0_model_infra/routing/modality_gate.py
Layer: Layer 0 - Routing Pipeline (Step 1)
Purpose: Detect modality and required capabilities BEFORE complexity analysis
Depends on: src/layer0_model_infra/config
Used by: Elite router

The modality gate is deterministic and lightweight.
Goal: Avoid calling heavy multimodal models unnecessarily.

SECURITY:
  InputValidator runs BEFORE modality analysis to reject:
    - Prompt injection patterns
    - Oversized inputs (> configurable max tokens)
    - Excessive attachments
    - Hidden Unicode control characters
    - Unsupported file types
"""

import hashlib
import re
import unicodedata
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.layer0_model_infra.config.routing_config import get_routing_config
from src.shared.logger import get_logger

logger = get_logger(__name__)
config = get_routing_config()


# ---------------------------------------------------------------------------
# Input Validation (Security Layer)
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """Result of input validation."""

    passed: bool = Field(..., description="Whether input passed all checks")
    rejected_reason: Optional[str] = Field(default=None, description="Why input was rejected")
    sanitized_text: str = Field(..., description="Cleaned text after sanitization")
    injection_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class InputValidator:
    """
    Security gate that runs BEFORE any routing logic.

    Rejects:
      - Prompt injection attempts
      - Oversized inputs
      - Excessive attachments
      - Hidden Unicode manipulation
      - Unsupported file types
    """

    # ── Prompt injection patterns ──────────────────────────────────────────
    INJECTION_PATTERNS: list[re.Pattern] = [
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+(a|an|the)?\s*\w+", re.IGNORECASE),
        re.compile(r"system:\s*override", re.IGNORECASE),
        re.compile(r"disregard\s+(all\s+)?prior\s+(context|instructions?|rules?)", re.IGNORECASE),
        re.compile(r"forget\s+(everything|all|your)\s+(you|instructions?|rules?)", re.IGNORECASE),
        re.compile(r"pretend\s+(you('re|\s+are)\s+)", re.IGNORECASE),
        re.compile(r"do\s+not\s+follow\s+(your|the)\s+(guidelines|rules|instructions)", re.IGNORECASE),
        re.compile(r"\[system\]|\[admin\]|\[override\]", re.IGNORECASE),
        re.compile(r"jailbreak|DAN\s+mode|developer\s+mode", re.IGNORECASE),
        re.compile(r"respond\s+without\s+(any\s+)?restrictions?", re.IGNORECASE),
    ]

    # ── Limits ─────────────────────────────────────────────────────────────
    MAX_CHAR_LENGTH: int = 128_000          # ~32K tokens
    MAX_ATTACHMENTS: int = 10
    MAX_ATTACHMENT_SIZE_MB: float = 25.0

    # ── Supported MIME categories ──────────────────────────────────────────
    SUPPORTED_MIME_PREFIXES: set[str] = {
        "text/", "image/", "audio/", "application/json", "text/csv",
        "application/pdf", "application/xml",
    }

    # ── Hidden Unicode control characters to strip ─────────────────────────
    HIDDEN_CHAR_CATEGORIES: set[str] = {"Cc", "Cf", "Co", "Cs"}
    # Keep standard whitespace
    KEEP_CHARS: set[int] = {0x09, 0x0A, 0x0D, 0x20}  # tab, LF, CR, space

    def validate(
        self,
        text: str,
        image_count: int = 0,
        file_types: Optional[list[str]] = None,
        attachment_sizes_mb: Optional[list[float]] = None,
    ) -> ValidationResult:
        """
        Validate and sanitize input before routing.

        Returns ValidationResult with `passed=False` if input should be rejected.
        """
        warnings: list[str] = []
        injection_score = 0.0

        # ── 1. Length check ────────────────────────────────────────────────
        if len(text) > self.MAX_CHAR_LENGTH:
            return ValidationResult(
                passed=False,
                rejected_reason=f"Input exceeds maximum length ({len(text):,} > {self.MAX_CHAR_LENGTH:,} chars)",
                sanitized_text=text[:100] + "...[TRUNCATED]",
                injection_risk_score=0.0,
            )

        # ── 2. Attachment count ────────────────────────────────────────────
        if image_count > self.MAX_ATTACHMENTS:
            return ValidationResult(
                passed=False,
                rejected_reason=f"Too many attachments ({image_count} > {self.MAX_ATTACHMENTS})",
                sanitized_text=text,
                injection_risk_score=0.0,
            )

        # ── 3. File type check ─────────────────────────────────────────────
        if file_types:
            for ft in file_types:
                if not any(ft.startswith(prefix) for prefix in self.SUPPORTED_MIME_PREFIXES):
                    return ValidationResult(
                        passed=False,
                        rejected_reason=f"Unsupported file type: {ft}",
                        sanitized_text=text,
                        injection_risk_score=0.0,
                    )

        if attachment_sizes_mb:
            for size_mb in attachment_sizes_mb:
                if size_mb > self.MAX_ATTACHMENT_SIZE_MB:
                    return ValidationResult(
                        passed=False,
                        rejected_reason=(
                            f"Attachment too large ({size_mb:.2f}MB > {self.MAX_ATTACHMENT_SIZE_MB:.2f}MB)"
                        ),
                        sanitized_text=text,
                        injection_risk_score=0.0,
                    )

        # ── 4. Sanitize hidden characters ──────────────────────────────────
        sanitized = self._strip_hidden_chars(text)
        if len(sanitized) < len(text):
            chars_removed = len(text) - len(sanitized)
            warnings.append(f"Stripped {chars_removed} hidden Unicode characters")

        # ── 5. Prompt injection detection ──────────────────────────────────
        injection_hits = 0
        for pattern in self.INJECTION_PATTERNS:
            if pattern.search(sanitized):
                injection_hits += 1

        injection_score = min(injection_hits / 3.0, 1.0)  # normalise to 0-1

        if injection_hits >= 2:
            logger.warning(
                "prompt_injection_detected",
                hits=injection_hits,
                score=injection_score,
                query_hash=hashlib.sha256(text.encode()).hexdigest()[:16],
            )
            return ValidationResult(
                passed=False,
                rejected_reason=f"Prompt injection risk detected (score={injection_score:.2f}, hits={injection_hits})",
                sanitized_text=sanitized[:100] + "...[BLOCKED]",
                injection_risk_score=injection_score,
            )

        if injection_hits == 1:
            warnings.append("Low-confidence injection pattern detected (single hit)")

        return ValidationResult(
            passed=True,
            sanitized_text=sanitized,
            injection_risk_score=injection_score,
            warnings=warnings,
        )

    def _strip_hidden_chars(self, text: str) -> str:
        """Remove hidden Unicode control characters while preserving normal whitespace."""
        cleaned = []
        for ch in text:
            code = ord(ch)
            if code in self.KEEP_CHARS:
                cleaned.append(ch)
            elif unicodedata.category(ch) not in self.HIDDEN_CHAR_CATEGORIES:
                cleaned.append(ch)
            # else: skip hidden character
        return "".join(cleaned)


# ---------------------------------------------------------------------------
# Modality Types
# ---------------------------------------------------------------------------


class InputModality(str, Enum):
    """Detected input modality."""

    TEXT_ONLY = "text_only"
    CODE_HEAVY = "code_heavy"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    STRUCTURED = "structured"      # JSON / CSV / tabular
    DOCUMENT = "document"
    MULTIMODAL = "multimodal"


class ModalityWeight(BaseModel):
    """Weighting of different modalities in input."""

    text_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    vision_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    audio_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    code_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    structured_weight: float = Field(default=0.0, ge=0.0, le=1.0)


class ModalityAnalysis(BaseModel):
    """Result of modality gate analysis."""

    primary_modality: InputModality = Field(..., description="Primary input type")
    weights: ModalityWeight = Field(..., description="Modality weights")
    requires_vision: bool = Field(default=False, description="Needs vision model")
    requires_audio: bool = Field(default=False, description="Needs audio model")
    requires_code_model: bool = Field(default=False, description="Needs code-specialized model")
    has_ocr_content: bool = Field(default=False, description="Contains OCR/text extraction")
    has_diagram: bool = Field(default=False, description="Contains diagrams/charts")
    reasoning: str = Field(..., description="Why this modality was detected")

    # ── New fields ────────────────────────────────────────────────────────
    language: str = Field(default="en", description="Detected natural language")
    token_count: int = Field(default=0, description="Estimated token count")
    contains_injection_risk: bool = Field(default=False, description="Injection pattern found")
    validation_passed: bool = Field(default=True, description="Input validation passed")
    code_density: float = Field(default=0.0, ge=0.0, le=1.0)
    code_language: str = Field(default="", description="Detected code language")
    table_density: float = Field(default=0.0, ge=0.0, le=1.0)
    ocr_required: bool = Field(default=False)
    multimodal_required: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Modality Gate
# ---------------------------------------------------------------------------


class ModalityGate:
    """
    Layer 1: Modality & Input Analysis.

    Detects what TYPE of input this is before any complexity reasoning.
    This is deterministic, fast, and cheap.

    Includes InputValidator as a security pre-check.
    """

    # Code indicators
    CODE_PATTERNS = [
        r'```[\w]*\n',           # Code blocks
        r'def\s+\w+\s*\(',      # Python functions
        r'class\s+\w+',         # Classes
        r'function\s+\w+\s*\(', # JavaScript functions
        r'import\s+\w+',        # Imports
        r'from\s+\w+\s+import', # Python imports
        r'<\w+>.*</\w+>',       # HTML/XML tags
        r'\{[\s\S]*:\s*[\s\S]*\}',  # JSON-like structures
        r'SELECT\s+.+\s+FROM',  # SQL
        r'CREATE\s+TABLE',      # DDL
    ]

    # OCR/document indicators
    DOCUMENT_KEYWORDS = [
        'extract text', 'read image', 'ocr', 'pdf', 'document',
        'scan', 'screenshot', 'table', 'chart', 'graph',
    ]

    # Diagram indicators
    DIAGRAM_KEYWORDS = [
        'diagram', 'flowchart', 'chart', 'plot', 'graph',
        'visualization', 'architecture', 'schematic',
    ]

    # Structured data indicators
    STRUCTURED_PATTERNS = [
        r'^\s*\{[\s\S]*\}\s*$',                     # Full JSON object
        r'^\s*\[[\s\S]*\]\s*$',                      # JSON array
        r'(\w+,){2,}\w+\n(\w+,){2,}',               # CSV-like rows
        r'"[\w]+"\s*:\s*("[^"]*"|\d+|true|false|null)', # JSON key-value
    ]

    # Video indicators
    VIDEO_KEYWORDS = [
        'video', 'clip', 'footage', 'recording', 'mp4', 'avi',
        'mov', 'watch this', 'play this',
    ]

    # Language detection patterns (lightweight)
    LANGUAGE_INDICATORS = {
        "zh": [r'[\u4e00-\u9fff]'],           # Chinese
        "ja": [r'[\u3040-\u309f\u30a0-\u30ff]'],  # Japanese
        "ko": [r'[\uac00-\ud7af]'],           # Korean
        "ar": [r'[\u0600-\u06ff]'],           # Arabic
        "hi": [r'[\u0900-\u097f]'],           # Hindi/Devanagari
        "ru": [r'[\u0400-\u04ff]'],           # Cyrillic
    }

    def __init__(self) -> None:
        self.validator = InputValidator()

    def analyze(
        self,
        text: str,
        has_images: bool = False,
        has_audio: bool = False,
        image_count: int = 0,
        has_video: bool = False,
        file_types: Optional[list[str]] = None,
        attachment_sizes_mb: Optional[list[float]] = None,
    ) -> ModalityAnalysis:
        """
        Analyze input modality with security validation.

        Args:
            text: Input text
            has_images: Whether images are attached
            has_audio: Whether audio is attached
            image_count: Number of images
            has_video: Whether video is attached
            file_types: MIME types of attached files

        Returns:
            Modality analysis with weights and requirements
        """
        # ── Security validation ────────────────────────────────────────────
        validation = self.validator.validate(
            text=text,
            image_count=image_count,
            file_types=file_types,
            attachment_sizes_mb=attachment_sizes_mb,
        )

        if not validation.passed:
            logger.warning(
                "input_validation_failed",
                reason=validation.rejected_reason,
            )
            return ModalityAnalysis(
                primary_modality=InputModality.TEXT_ONLY,
                weights=ModalityWeight(),
                reasoning=f"BLOCKED: {validation.rejected_reason}",
                validation_passed=False,
                contains_injection_risk=validation.injection_risk_score > 0.3,
                token_count=len(text) // 4,
            )

        # Work with sanitized text
        clean_text = validation.sanitized_text
        text_lower = clean_text.lower()

        # ── Estimate tokens ────────────────────────────────────────────────
        token_count = len(clean_text) // 4  # rough: 4 chars ≈ 1 token

        # ── Detect language ────────────────────────────────────────────────
        language = self._detect_language(clean_text)

        # ── Initialize weights ─────────────────────────────────────────────
        weights = ModalityWeight()

        # Detect code content
        code_density = self._calculate_code_density(clean_text)
        weights.code_weight = code_density
        code_language = self._detect_code_language(clean_text)

        # Detect structured data
        structured_density = self._detect_structured_data(clean_text)
        weights.structured_weight = structured_density
        table_density = self._detect_table_density(clean_text)

        # Detect vision requirements
        if has_images:
            weights.vision_weight = 0.8
            has_ocr = any(kw in text_lower for kw in self.DOCUMENT_KEYWORDS)
            has_diagram = any(kw in text_lower for kw in self.DIAGRAM_KEYWORDS)
            if has_diagram:
                weights.vision_weight = 1.0
        else:
            has_ocr = False
            has_diagram = False

        # Detect audio requirements
        if has_audio:
            weights.audio_weight = 1.0

        # Adjust text weight
        weights.text_weight = 1.0 - max(
            weights.vision_weight,
            weights.audio_weight,
            weights.code_weight * 0.5,
            weights.structured_weight * 0.5,
        )

        # ── Determine primary modality ─────────────────────────────────────
        primary_modality = self._determine_primary_modality(
            weights, has_images, has_audio, has_video, code_density, structured_density,
            text_lower,
        )

        # Determine requirements
        requires_vision = has_images or has_ocr or has_diagram
        requires_audio = has_audio
        requires_code_model = code_density > 0.3
        multimodal_required = sum(
            [
                int(requires_vision),
                int(requires_audio),
                int(requires_code_model),
                int(structured_density > 0.5),
            ]
        ) >= 2

        # Generate reasoning
        reasoning = self._generate_reasoning(
            primary_modality, weights, has_images, has_audio,
            code_density, has_ocr, has_diagram, has_video, structured_density,
        )

        analysis = ModalityAnalysis(
            primary_modality=primary_modality,
            weights=weights,
            requires_vision=requires_vision,
            requires_audio=requires_audio,
            requires_code_model=requires_code_model,
            has_ocr_content=has_ocr,
            has_diagram=has_diagram,
            reasoning=reasoning,
            language=language,
            token_count=token_count,
            contains_injection_risk=validation.injection_risk_score > 0.0,
            validation_passed=True,
            code_density=code_density,
            code_language=code_language,
            table_density=table_density,
            ocr_required=has_ocr,
            multimodal_required=multimodal_required,
        )

        logger.debug(
            "modality_gate_analysis",
            primary_modality=primary_modality.value,
            vision_weight=weights.vision_weight,
            code_weight=weights.code_weight,
            language=language,
            token_count=token_count,
        )

        return analysis

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _calculate_code_density(self, text: str) -> float:
        """Calculate code density (0-1)."""
        if not text:
            return 0.0
        code_matches = 0
        for pattern in self.CODE_PATTERNS:
            code_matches += len(re.findall(pattern, text, re.MULTILINE))
        density = min(code_matches / max(len(text) / 100, 1), 1.0)
        return density

    def _detect_structured_data(self, text: str) -> float:
        """Detect structured data (JSON, CSV) content density."""
        if not text:
            return 0.0
        hits = 0
        for pattern in self.STRUCTURED_PATTERNS:
            if re.search(pattern, text, re.MULTILINE | re.DOTALL):
                hits += 1
        return min(hits / 2.0, 1.0)

    def _detect_table_density(self, text: str) -> float:
        """Estimate table-like content density (markdown, CSV, tab-separated)."""
        if not text:
            return 0.0
        hits = 0
        if re.search(r'^\s*\|.+\|\s*$', text, re.MULTILINE):
            hits += 1
        if re.search(r'^\s*[^,\n]+,[^,\n]+,[^,\n]+', text, re.MULTILINE):
            hits += 1
        if "\t" in text:
            hits += 1
        return min(hits / 3.0, 1.0)

    def _detect_code_language(self, text: str) -> str:
        """Best-effort code language detection from fences and syntax cues."""
        if not text:
            return ""

        fenced = re.search(r"```(\w+)", text)
        if fenced:
            return fenced.group(1).lower()

        lowered = text.lower()
        if "def " in lowered and "import " in lowered:
            return "python"
        if "function " in lowered or "const " in lowered or "=> " in lowered:
            return "javascript"
        if "public class " in lowered:
            return "java"
        if "#include" in lowered:
            return "cpp"
        if "select " in lowered and " from " in lowered:
            return "sql"
        return ""

    def _detect_language(self, text: str) -> str:
        """Lightweight language detection based on Unicode script."""
        for lang, patterns in self.LANGUAGE_INDICATORS.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    # Count how many characters match
                    matches = len(re.findall(pattern, text))
                    if matches >= 3:
                        return lang
        return "en"

    def _determine_primary_modality(
        self,
        weights: ModalityWeight,
        has_images: bool,
        has_audio: bool,
        has_video: bool,
        code_density: float,
        structured_density: float,
        text_lower: str,
    ) -> InputModality:
        """Determine the primary modality from weights."""

        # Video takes highest precedence
        if has_video or any(kw in text_lower for kw in self.VIDEO_KEYWORDS):
            if has_video:
                return InputModality.VIDEO

        # Multimodal if multiple high weights
        high_weights = sum([
            weights.vision_weight > 0.5,
            weights.audio_weight > 0.5,
            weights.code_weight > 0.5,
            weights.structured_weight > 0.5,
        ])
        if high_weights >= 2:
            return InputModality.MULTIMODAL

        # Vision dominant
        if weights.vision_weight > 0.6:
            return InputModality.IMAGE

        # Audio dominant
        if weights.audio_weight > 0.6:
            return InputModality.AUDIO

        # Structured data dominant
        if structured_density > 0.5:
            return InputModality.STRUCTURED

        # Code dominant
        if code_density > 0.4:
            return InputModality.CODE_HEAVY

        # Default to text
        return InputModality.TEXT_ONLY

    def _generate_reasoning(
        self,
        primary_modality: InputModality,
        weights: ModalityWeight,
        has_images: bool,
        has_audio: bool,
        code_density: float,
        has_ocr: bool,
        has_diagram: bool,
        has_video: bool = False,
        structured_density: float = 0.0,
    ) -> str:
        """Generate human-readable reasoning."""
        reasons = []

        if primary_modality == InputModality.VIDEO:
            reasons.append("Video input detected")
        elif primary_modality == InputModality.IMAGE:
            if has_ocr:
                reasons.append("Image with OCR/text extraction needs")
            elif has_diagram:
                reasons.append("Image contains diagrams/charts requiring vision analysis")
            else:
                reasons.append("Image input detected")
        elif primary_modality == InputModality.AUDIO:
            reasons.append("Audio input requires speech processing")
        elif primary_modality == InputModality.STRUCTURED:
            reasons.append(f"Structured data detected (density={structured_density:.2f})")
        elif primary_modality == InputModality.CODE_HEAVY:
            reasons.append(f"High code density ({code_density:.2f})")
        elif primary_modality == InputModality.MULTIMODAL:
            reasons.append("Multiple input modalities detected")
        else:
            reasons.append("Text-only input")

        if weights.vision_weight > 0:
            reasons.append(f"vision={weights.vision_weight:.2f}")
        if weights.code_weight > 0:
            reasons.append(f"code={weights.code_weight:.2f}")
        if weights.structured_weight > 0:
            reasons.append(f"structured={weights.structured_weight:.2f}")

        return "; ".join(reasons)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_modality_gate: Optional[ModalityGate] = None


def get_modality_gate() -> ModalityGate:
    """Get global modality gate instance."""
    global _modality_gate
    if _modality_gate is None:
        _modality_gate = ModalityGate()
    return _modality_gate
