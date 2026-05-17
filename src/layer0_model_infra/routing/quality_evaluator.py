"""
📁 File: src/layer0_model_infra/routing/quality_evaluator.py
Layer: Layer 0 - Routing Pipeline (Step 7)
Purpose: Evaluate output quality to detect silent failures
Depends on: src/layer0_model_infra/config, gateway
Used by: Elite router, escalation engine

Three-stage evaluation pipeline:
  Stage 1: Deterministic Validators (JSON, code, schema, format) — fast, zero LLM cost
  Stage 2: Enhanced Heuristics (truncation, coherence, refusal, hallucination)
  Stage 3: LLM Judge Fallback — only invoked when deterministic checks are inconclusive
"""

import ast
import json
import re
from typing import Optional

from pydantic import BaseModel, Field

from src.layer0_model_infra.config.routing_config import get_routing_config
from src.shared.logger import get_logger

logger = get_logger(__name__)
config = get_routing_config()


class QualityScore(BaseModel):
    """Quality evaluation score."""

    overall_quality: float = Field(..., ge=0.0, le=1.0, description="Overall quality (0-1)")

    # Component scores (existing)
    completeness_score: float = Field(default=1.0, ge=0.0, le=1.0)
    coherence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    refusal_detected: bool = Field(default=False)
    hallucination_risk: float = Field(default=0.0, ge=0.0, le=1.0)

    # ── New: Stage scores ──────────────────────────────────────────────────
    validator_score: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Deterministic validator score (1.0 = all pass)",
    )
    heuristic_score: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Enhanced heuristic score",
    )
    judge_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="LLM judge score (None if not invoked)",
    )

    validators_run: list[str] = Field(
        default_factory=list, description="Which validators were executed",
    )
    validator_failures: list[str] = Field(
        default_factory=list, description="Which validators failed",
    )

    passes_threshold: bool = Field(..., description="Whether quality is acceptable")
    needs_escalation: bool = Field(..., description="Whether to escalate")
    reasoning: str = Field(..., description="Quality assessment reasoning")


class QualityEvaluator:
    """
    Layer 7: Output Quality Evaluation.

    Three-stage pipeline:
    1. Deterministic validators (JSON validity, code compilation, format compliance)
    2. Enhanced heuristics (truncation, coherence, hallucination, refusal)
    3. LLM judge fallback (structured scoring when stages 1-2 are inconclusive)
    """

    # Refusal patterns
    REFUSAL_PATTERNS = [
        re.compile(r"i cannot|i can't|i'm unable|i am unable", re.IGNORECASE),
        re.compile(r"i don't have|i do not have", re.IGNORECASE),
        re.compile(r"as an ai|as a language model", re.IGNORECASE),
        re.compile(r"i apologize, but|i'm sorry, but", re.IGNORECASE),
        re.compile(r"sorry, i cannot|sorry, i can't", re.IGNORECASE),
        re.compile(r"i'm not able to|i am not able to", re.IGNORECASE),
    ]

    # Hedging patterns
    HEDGING_PATTERNS = [
        re.compile(r"maybe|perhaps|possibly|might be", re.IGNORECASE),
        re.compile(r"i think|i believe|in my opinion", re.IGNORECASE),
        re.compile(r"it seems|it appears|it looks like", re.IGNORECASE),
    ]

    # Hallucination indicators
    HALLUCINATION_INDICATORS = [
        re.compile(r"according to .* sources", re.IGNORECASE),
        re.compile(r"studies show|research indicates|experts say", re.IGNORECASE),
        re.compile(r"in a study published in", re.IGNORECASE),
        re.compile(r"as documented in", re.IGNORECASE),
    ]

    # Truncation indicators
    TRUNCATION_INDICATORS = [
        r'\.{3}\s*$',                     # ends with ...
        r'(?:and|but|or|the|a|in)\s*$',   # ends mid-sentence
        r'```\s*$',                        # unclosed code block at end
        r'\{\s*$',                         # unclosed brace
        r'\[\s*$',                         # unclosed bracket
    ]

    def evaluate(
        self,
        response: str,
        query: str,
        model_id: str,
        required_format: Optional[str] = None,
        expected_schema: Optional[dict] = None,
        use_judge: bool = False,
    ) -> QualityScore:
        """
        Evaluate response quality using the 3-stage pipeline.

        Stage 1: Deterministic validators (if applicable)
        Stage 2: Enhanced heuristics (always)
        Stage 3: LLM judge (only when invoked or when stages 1-2 are inconclusive)
        """
        validators_run: list[str] = []
        validator_failures: list[str] = []

        # ═══════════════════════════════════════════════════════════════════
        # STAGE 1: Deterministic Validators
        # ═══════════════════════════════════════════════════════════════════
        validator_score = self._run_deterministic_validators(
            response, query, required_format, expected_schema,
            validators_run, validator_failures,
        )

        # ═══════════════════════════════════════════════════════════════════
        # STAGE 2: Enhanced Heuristics
        # ═══════════════════════════════════════════════════════════════════
        completeness = self._evaluate_completeness(response, query)
        coherence = self._evaluate_coherence(response)
        refusal = self._detect_refusal(response)
        hallucination_risk = self._estimate_hallucination_risk(response)
        truncated = self._detect_truncation(response)
        format_missing = self._detect_missing_format(response, required_format)

        # Heuristic score aggregation
        if refusal:
            heuristic_score = 0.0
        else:
            heuristic_score = (
                completeness * 0.30
                + coherence * 0.25
                + (1.0 - hallucination_risk) * 0.20
                + (0.0 if truncated else 1.0) * 0.15
                + (0.0 if format_missing else 1.0) * 0.10
            )

        # ═══════════════════════════════════════════════════════════════════
        # STAGE 3: LLM Judge (optional)
        # ═══════════════════════════════════════════════════════════════════
        judge_score: Optional[float] = None
        if use_judge:
            judge_score = self._invoke_llm_judge(response, query, model_id)

        # ═══════════════════════════════════════════════════════════════════
        # OVERALL QUALITY (weighted combination of all stages)
        # ═══════════════════════════════════════════════════════════════════
        if refusal:
            overall = 0.0
        elif judge_score is not None:
            overall = (
                validator_score * 0.25
                + heuristic_score * 0.30
                + judge_score * 0.45
            )
        else:
            overall = (
                validator_score * 0.35
                + heuristic_score * 0.65
            )

        # Threshold check
        threshold = config.quality_eval.min_quality_score
        passes_threshold = overall >= threshold and not refusal
        needs_escalation = not passes_threshold or overall < 0.6

        reasoning = self._generate_reasoning(
            completeness, coherence, refusal, hallucination_risk, overall,
            validator_failures, truncated, format_missing, judge_score,
        )

        score = QualityScore(
            overall_quality=round(overall, 4),
            completeness_score=completeness,
            coherence_score=coherence,
            refusal_detected=refusal,
            hallucination_risk=hallucination_risk,
            validator_score=validator_score,
            heuristic_score=round(heuristic_score, 4),
            judge_score=judge_score,
            validators_run=validators_run,
            validator_failures=validator_failures,
            passes_threshold=passes_threshold,
            needs_escalation=needs_escalation,
            reasoning=reasoning,
        )

        logger.debug(
            "quality_evaluated",
            model=model_id,
            quality=round(overall, 4),
            validator_score=validator_score,
            heuristic_score=round(heuristic_score, 4),
            judge_score=judge_score,
            passes=passes_threshold,
            needs_escalation=needs_escalation,
            validator_failures=validator_failures,
        )

        return score

    # ------------------------------------------------------------------
    # STAGE 1: Deterministic Validators
    # ------------------------------------------------------------------

    def _run_deterministic_validators(
        self,
        response: str,
        query: str,
        required_format: Optional[str],
        expected_schema: Optional[dict],
        validators_run: list[str],
        validator_failures: list[str],
    ) -> float:
        """Run applicable deterministic validators. Returns validator_score (0-1)."""
        passed = 0
        total = 0

        # 1. JSON validity check
        if self._should_check_json(response, required_format):
            validators_run.append("json_validity")
            total += 1
            if self._validate_json(response):
                passed += 1
            else:
                validator_failures.append("json_validity: invalid JSON")

        # 2. Python code compilation check
        if self._should_check_code(response, required_format):
            validators_run.append("code_compilation")
            total += 1
            if self._validate_python_code(response):
                passed += 1
            else:
                validator_failures.append("code_compilation: syntax error")

        # 3. Format compliance check
        if required_format and required_format not in ("unknown", "prose"):
            validators_run.append("format_compliance")
            total += 1
            if self._validate_format_compliance(response, required_format):
                passed += 1
            else:
                validator_failures.append(f"format_compliance: expected {required_format}")

        # 4. Schema validation (if schema provided)
        if expected_schema:
            validators_run.append("schema_validation")
            total += 1
            if self._validate_schema(response, expected_schema):
                passed += 1
            else:
                validator_failures.append("schema_validation: schema mismatch")

        if total == 0:
            return 1.0  # No validators applicable → assume pass
        return passed / total

    def _should_check_json(self, response: str, required_format: Optional[str]) -> bool:
        """Determine if JSON validation should run."""
        if required_format == "json":
            return True
        # Check if response looks like JSON
        stripped = response.strip()
        return stripped.startswith("{") or stripped.startswith("[")

    def _validate_json(self, response: str) -> bool:
        """Validate that response is parseable JSON."""
        try:
            # Extract JSON from response (may be wrapped in markdown code block)
            text = self._extract_code_content(response, "json")
            json.loads(text)
            return True
        except (json.JSONDecodeError, ValueError):
            return False

    def _should_check_code(self, response: str, required_format: Optional[str]) -> bool:
        """Determine if code compilation check should run."""
        if required_format == "code":
            return True
        # Check if response contains Python code blocks
        return bool(re.search(r'```python\n', response))

    def _validate_python_code(self, response: str) -> bool:
        """Validate Python code compiles (syntax check only, no execution)."""
        try:
            code = self._extract_code_content(response, "python")
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def _validate_format_compliance(self, response: str, required_format: str) -> bool:
        """Check if response matches the requested format."""
        if required_format == "json":
            return self._validate_json(response)
        elif required_format == "table":
            # Check for table-like structure (markdown tables or tabular data)
            return bool(re.search(r'\|.*\|.*\|', response)) or bool(re.search(r'\t.*\t', response))
        elif required_format == "list":
            # Check for bullet/numbered lists
            return bool(re.search(r'[\n\r]\s*[-*•]\s', response) or re.search(r'[\n\r]\s*\d+\.\s', response))
        elif required_format == "code":
            return bool(re.search(r'```', response)) or self._validate_python_code(response)
        elif required_format == "markdown":
            return bool(re.search(r'#{1,6}\s', response) or re.search(r'\*\*.*\*\*', response))
        return True  # Unknown format → pass

    def _validate_schema(self, response: str, schema: dict) -> bool:
        """Validate JSON response against a simple schema (required keys check)."""
        try:
            text = self._extract_code_content(response, "json")
            data = json.loads(text)
            # Simple check: verify required keys exist
            required_keys = schema.get("required", [])
            if isinstance(data, dict):
                return all(key in data for key in required_keys)
            return True
        except (json.JSONDecodeError, ValueError):
            return False

    @staticmethod
    def _extract_code_content(response: str, language: str = "") -> str:
        """Extract code from markdown code blocks or raw response."""
        # Try to extract from code block
        pattern = rf'```{language}\s*\n([\s\S]*?)```'
        match = re.search(pattern, response)
        if match:
            return match.group(1).strip()
        # Try generic code block
        match = re.search(r'```\s*\n([\s\S]*?)```', response)
        if match:
            return match.group(1).strip()
        return response.strip()

    # ------------------------------------------------------------------
    # STAGE 2: Enhanced Heuristics
    # ------------------------------------------------------------------

    def _evaluate_completeness(self, response: str, query: str) -> float:
        """Check if response is complete."""
        if len(response) < 20:
            return 0.3

        query_length = len(query.split())
        response_length = len(response.split())

        if response_length < query_length * 0.5:
            return 0.5

        # Check for incomplete sentences
        if response.rstrip().endswith(('...', 'and', 'but', 'or', 'the', 'a')):
            return 0.6

        return 1.0

    def _evaluate_coherence(self, response: str) -> float:
        """Check logical coherence."""
        response_lower = response.lower()

        # Check for contradictions
        has_contradiction = (
            'however' in response_lower and 'but' in response_lower
            and response_lower.count('however') > 1
        ) or (
            response_lower.startswith('yes') and 'no' in response_lower.split('.')[0]
        )

        if has_contradiction:
            return 0.6

        hedging_count = sum(
            1 for pattern in self.HEDGING_PATTERNS
            if pattern.search(response)
        )

        if hedging_count > 3:
            return 0.7

        return 1.0

    def _detect_refusal(self, response: str) -> bool:
        """Detect if model refused to answer."""
        # Only flag as refusal if it's in the first 200 chars (not a mid-response caveat)
        first_part = response[:200]
        for pattern in self.REFUSAL_PATTERNS:
            if pattern.search(first_part):
                return True
        return False

    def _estimate_hallucination_risk(self, response: str) -> float:
        """Estimate risk of hallucination."""
        risk = 0.0
        for pattern in self.HALLUCINATION_INDICATORS:
            if pattern.search(response):
                risk += 0.2
        # Vague language without specifics
        if len(re.findall(r'\d+', response)) == 0 and len(response) > 200:
            risk += 0.1
        return min(risk, 1.0)

    def _detect_truncation(self, response: str) -> bool:
        """Detect if output was truncated mid-generation."""
        if not response:
            return True

        for pattern in self.TRUNCATION_INDICATORS:
            if re.search(pattern, response):
                return True

        # Check for unbalanced delimiters
        if response.count('```') % 2 != 0:
            return True
        if response.count('{') > response.count('}'):
            return True
        if response.count('[') > response.count(']'):
            return True
        if response.count('(') > response.count(')') + 1:
            return True

        return False

    def _detect_missing_format(self, response: str, required_format: Optional[str]) -> bool:
        """Detect if the requested output format is missing."""
        if not required_format or required_format in ("unknown", "prose"):
            return False

        if required_format == "json":
            return not ('{' in response or '[' in response)
        elif required_format == "table":
            return not ('|' in response or '\t' in response)
        elif required_format == "list":
            return not bool(re.search(r'[-*•]\s|\d+\.\s', response))
        elif required_format == "code":
            return not ('```' in response or 'def ' in response or 'function ' in response)
        return False

    # ------------------------------------------------------------------
    # STAGE 3: LLM Judge
    # ------------------------------------------------------------------

    def _invoke_llm_judge(
        self, response: str, query: str, model_id: str
    ) -> Optional[float]:
        """
        Invoke LLM judge for quality assessment.

        Uses the configured quality eval model to score the response
        on accuracy, completeness, coherence, and safety.
        """
        try:
            from src.layer0_model_infra.gateway import LLMRequest, get_gateway

            gateway = get_gateway()

            judge_prompt = (
                "You are a strict quality evaluator. Score the following AI response to a user query.\n\n"
                f"USER QUERY: {query[:500]}\n\n"
                f"AI RESPONSE: {response[:2000]}\n\n"
                "Score each dimension from 1-5:\n"
                "1. Accuracy: Is the information correct?\n"
                "2. Completeness: Does it fully address the query?\n"
                "3. Coherence: Is it well-structured and logical?\n"
                "4. Safety: Is it free from harmful content?\n\n"
                "Respond ONLY with a JSON object: "
                '{"accuracy": N, "completeness": N, "coherence": N, "safety": N}\n'
                "No explanation needed."
            )

            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context — can't call synchronously
                # Return None; the judge will be invoked asynchronously elsewhere
                logger.debug("llm_judge_skipped_sync_context")
                return None
            except RuntimeError:
                pass

            # Synchronous judge call (for non-async contexts)
            request = LLMRequest(
                model_id=config.quality_eval.model,
                messages=[{"role": "user", "content": judge_prompt}],
                temperature=0.1,
                max_tokens=100,
            )

            import asyncio
            result = asyncio.run(gateway.complete(request))

            # Parse judge response
            try:
                scores = json.loads(result.content)
                avg = sum(scores.values()) / len(scores)
                return avg / 5.0  # Normalise 1-5 → 0-1
            except (json.JSONDecodeError, AttributeError):
                logger.warning("llm_judge_parse_failed", content=result.content[:100])
                return None

        except Exception as e:
            logger.error("llm_judge_failed", error=str(e))
            return None

    # ------------------------------------------------------------------
    # Reasoning
    # ------------------------------------------------------------------

    def _generate_reasoning(
        self,
        completeness: float,
        coherence: float,
        refusal: bool,
        hallucination_risk: float,
        overall: float,
        validator_failures: list[str],
        truncated: bool = False,
        format_missing: bool = False,
        judge_score: Optional[float] = None,
    ) -> str:
        """Generate human-readable reasoning."""
        reasons = []

        if refusal:
            reasons.append("REFUSAL detected")
        if validator_failures:
            reasons.append(f"validator failures: {', '.join(validator_failures)}")
        if truncated:
            reasons.append("output appears truncated")
        if format_missing:
            reasons.append("requested format missing")
        if completeness < 0.7:
            reasons.append(f"low completeness ({completeness:.2f})")
        if coherence < 0.7:
            reasons.append(f"low coherence ({coherence:.2f})")
        if hallucination_risk > 0.3:
            reasons.append(f"hallucination risk ({hallucination_risk:.2f})")
        if judge_score is not None and judge_score < 0.6:
            reasons.append(f"LLM judge score low ({judge_score:.2f})")

        if not reasons:
            reasons.append(f"good quality ({overall:.2f})")

        return "; ".join(reasons)


# Global instance
_quality_evaluator: Optional[QualityEvaluator] = None


def get_quality_evaluator() -> QualityEvaluator:
    """Get global quality evaluator instance."""
    global _quality_evaluator
    if _quality_evaluator is None:
        _quality_evaluator = QualityEvaluator()
    return _quality_evaluator
