"""
📁 File: src/layer0_model_infra/routing/test_time_compute.py
Layer: Layer 0 (Model Infrastructure)
Purpose: Test-Time Compute Scaling (Layer 6)
Depends on: gateway.py, quality_evaluator.py
Used by: execution_loop.py

Implements three TTC strategies:

1. **Best-of-N** — generate N responses with varied temperature, pick highest quality.
   Best for: creative / planning queries.

2. **Self-Consistency** — generate N responses, extract answers, return majority answer.
   Best for: factual / QA / math queries with a single correct answer.

3. **Generator-Verifier** — generate one response, verify with quality model,
   regenerate on failure. Best for: coding / analysis where verification is cheap.
"""

import re
from collections import Counter
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from src.layer0_model_infra.gateway import LLMRequest, LLMResponse, get_gateway
from src.layer0_model_infra.routing.quality_evaluator import get_quality_evaluator
from src.shared.logger import get_logger

logger = get_logger(__name__)


class TTCStrategy(str, Enum):
    """Available TTC strategies."""
    BEST_OF_N = "best_of_n"
    SELF_CONSISTENCY = "self_consistency"
    GENERATOR_VERIFIER = "generator_verifier"


class TestTimeComputeDecision(BaseModel):
    """Decision on whether to use test-time compute."""

    should_use: bool = Field(..., description="Whether to use TTC")
    strategy: TTCStrategy = Field(default=TTCStrategy.BEST_OF_N, description="TTC strategy")
    num_samples: int = Field(default=1, description="Number of samples to generate")
    reasoning: str = Field(..., description="Why this decision was made")


class TestTimeComputeResult(BaseModel):
    """Result of test-time compute."""

    best_response: str
    best_quality: float
    strategy_used: TTCStrategy
    all_responses: List[str]
    all_qualities: List[float]
    samples_generated: int
    consensus_count: int = Field(default=0, description="How many agreed (self_consistency)")
    verification_passed: bool = Field(default=True, description="Verifier result (gen_verifier)")


class TestTimeComputeEngine:
    """
    Conditional Test-Time Compute Scaling.

    Uses different strategies depending on query type:
    - Best-of-N:          moderate complexity, creative/planning tasks
    - Self-Consistency:   factual/QA/math tasks with one correct answer
    - Generator-Verifier: coding/analysis tasks needing structured verification

    Avoids:
    - Trivial queries (waste of compute)
    - Expert queries (escalate instead)
    """

    def __init__(self):
        self.gateway = get_gateway()
        self.quality_evaluator = get_quality_evaluator()

    def should_use_ttc(
        self,
        uncertainty_score: float,
        complexity_band: str,
        user_tier: str,
        domain: str,
        intent: str = "",
        task_type: str = "",
    ) -> TestTimeComputeDecision:
        """
        Decide whether to use test-time compute and which strategy.

        Rules:
        1. Only for moderate uncertainty (0.4 - 0.6)
        2. Skip for trivial/expert queries
        3. Strategy selection based on task type / intent
        4. Premium users get more samples
        """
        # Rule 1: Uncertainty must be moderate
        if uncertainty_score < 0.4:
            return TestTimeComputeDecision(
                should_use=False,
                num_samples=1,
                reasoning="High confidence, single sample sufficient",
            )

        if uncertainty_score > 0.6:
            return TestTimeComputeDecision(
                should_use=False,
                num_samples=1,
                reasoning="High uncertainty, escalation preferred over TTC",
            )

        # Rule 2: Skip trivial queries
        if complexity_band in ["trivial", "simple"]:
            return TestTimeComputeDecision(
                should_use=False,
                num_samples=1,
                reasoning="Too simple for test-time compute",
            )

        # Rule 3: Skip expert-level (escalate instead)
        if complexity_band == "expert":
            return TestTimeComputeDecision(
                should_use=False,
                num_samples=1,
                reasoning="Expert query, escalation preferred",
            )

        # Rule 4: Select strategy based on task type / intent
        strategy = self._select_strategy(intent, task_type, domain)

        # Rule 5: Premium users get more samples
        if strategy == TTCStrategy.GENERATOR_VERIFIER:
            num_samples = 3  # max regeneration attempts
        else:
            num_samples = 3 if user_tier == "premium" else 2

        # Rule 6: Only for moderate/complex
        if complexity_band in ["moderate", "complex"]:
            return TestTimeComputeDecision(
                should_use=True,
                strategy=strategy,
                num_samples=num_samples,
                reasoning=(
                    f"Moderate uncertainty + {complexity_band} complexity → "
                    f"{strategy.value} with {num_samples} samples"
                ),
            )

        # Default: no TTC
        return TestTimeComputeDecision(
            should_use=False,
            num_samples=1,
            reasoning="Default: single sample",
        )

    def _select_strategy(
        self, intent: str, task_type: str, domain: str
    ) -> TTCStrategy:
        """Select TTC strategy based on query characteristics."""

        # Self-consistency for factual / QA / math
        if task_type in ("qa", "conversation") or intent in ("question_answering", "factual"):
            return TTCStrategy.SELF_CONSISTENCY

        # Generator-verifier for coding / analysis
        if task_type in ("analysis",) or intent in (
            "coding", "debugging", "code_review"
        ):
            return TTCStrategy.GENERATOR_VERIFIER

        # Best-of-N for creative / generation / transformation
        return TTCStrategy.BEST_OF_N

    # ------------------------------------------------------------------
    # Execution methods
    # ------------------------------------------------------------------

    async def execute(
        self,
        request: LLMRequest,
        decision: TestTimeComputeDecision,
        query: str,
    ) -> TestTimeComputeResult:
        """
        Route to the appropriate TTC strategy.
        """
        if decision.strategy == TTCStrategy.SELF_CONSISTENCY:
            return await self.generate_self_consistency(request, decision.num_samples, query)
        elif decision.strategy == TTCStrategy.GENERATOR_VERIFIER:
            return await self.generate_with_verification(request, decision.num_samples, query)
        else:
            return await self.generate_best_of_n(request, decision.num_samples, query)

    async def generate_best_of_n(
        self,
        request: LLMRequest,
        n: int,
        query: str,
    ) -> TestTimeComputeResult:
        """
        Generate N responses and return the best one.

        "Best" is determined by quality evaluation.
        """
        logger.info("ttc_best_of_n_started", n=n, model=request.model_id)

        responses: List[str] = []
        qualities: List[float] = []

        for i in range(n):
            # Vary temperature for diversity
            sample_request = request.model_copy()
            sample_request.temperature = request.temperature + (i * 0.1)

            response = await self.gateway.complete(sample_request)

            quality_score = self.quality_evaluator.evaluate(
                response=response.content,
                query=query,
                model_id=request.model_id,
            )

            responses.append(response.content)
            qualities.append(quality_score.overall_quality)

            logger.debug("ttc_sample", sample=i + 1, quality=quality_score.overall_quality)

        best_idx = qualities.index(max(qualities))

        logger.info(
            "ttc_best_of_n_done",
            best_sample=best_idx + 1,
            best_quality=qualities[best_idx],
        )

        return TestTimeComputeResult(
            best_response=responses[best_idx],
            best_quality=qualities[best_idx],
            strategy_used=TTCStrategy.BEST_OF_N,
            all_responses=responses,
            all_qualities=qualities,
            samples_generated=n,
        )

    async def generate_self_consistency(
        self,
        request: LLMRequest,
        n: int,
        query: str,
    ) -> TestTimeComputeResult:
        """
        Self-Consistency: Generate N responses, extract answers, return majority.

        1. Generate N responses at temperature=0.7
        2. Extract the "answer" from each (last sentence or conclusion)
        3. Return the answer appearing in the majority
        """
        logger.info("ttc_self_consistency_started", n=n, model=request.model_id)

        responses: List[str] = []
        qualities: List[float] = []
        extracted_answers: List[str] = []

        for i in range(n):
            sample_request = request.model_copy()
            sample_request.temperature = 0.7  # fixed temp for self-consistency

            response = await self.gateway.complete(sample_request)
            responses.append(response.content)

            quality_score = self.quality_evaluator.evaluate(
                response=response.content,
                query=query,
                model_id=request.model_id,
            )
            qualities.append(quality_score.overall_quality)

            # Extract "answer" from response
            answer = self._extract_answer(response.content)
            extracted_answers.append(answer)

        # Find majority answer
        answer_counts = Counter(extracted_answers)
        majority_answer, consensus_count = answer_counts.most_common(1)[0]

        # Find the best-quality response that gives the majority answer
        best_idx = 0
        best_q = 0.0
        for i, (ans, q) in enumerate(zip(extracted_answers, qualities)):
            if ans == majority_answer and q > best_q:
                best_idx = i
                best_q = q

        logger.info(
            "ttc_self_consistency_done",
            consensus=consensus_count,
            total=n,
            majority_answer_len=len(majority_answer),
        )

        return TestTimeComputeResult(
            best_response=responses[best_idx],
            best_quality=best_q,
            strategy_used=TTCStrategy.SELF_CONSISTENCY,
            all_responses=responses,
            all_qualities=qualities,
            samples_generated=n,
            consensus_count=consensus_count,
        )

    async def generate_with_verification(
        self,
        request: LLMRequest,
        max_attempts: int,
        query: str,
    ) -> TestTimeComputeResult:
        """
        Generator-Verifier: Generate → Verify → Regenerate if needed.

        1. Generate one response at standard temperature
        2. Evaluate quality (deterministic + heuristic checks)
        3. If quality < threshold, regenerate with higher temperature
        4. Return the first response that passes verification
        """
        logger.info("ttc_generator_verifier_started", max_attempts=max_attempts, model=request.model_id)

        responses: List[str] = []
        qualities: List[float] = []
        verification_passed = False

        for attempt in range(max_attempts):
            sample_request = request.model_copy()
            # Increase temperature on each attempt for diversity
            sample_request.temperature = min(request.temperature + (attempt * 0.15), 1.2)

            response = await self.gateway.complete(sample_request)
            responses.append(response.content)

            quality_score = self.quality_evaluator.evaluate(
                response=response.content,
                query=query,
                model_id=request.model_id,
            )
            qualities.append(quality_score.overall_quality)

            logger.debug(
                "ttc_verifier_check",
                attempt=attempt + 1,
                quality=quality_score.overall_quality,
                passed=quality_score.passes_threshold,
            )

            if quality_score.passes_threshold and quality_score.overall_quality >= 0.7:
                verification_passed = True
                break

        # Select best quality response across all attempts
        best_idx = qualities.index(max(qualities))

        logger.info(
            "ttc_generator_verifier_done",
            attempts=len(responses),
            verification_passed=verification_passed,
            best_quality=qualities[best_idx],
        )

        return TestTimeComputeResult(
            best_response=responses[best_idx],
            best_quality=qualities[best_idx],
            strategy_used=TTCStrategy.GENERATOR_VERIFIER,
            all_responses=responses,
            all_qualities=qualities,
            samples_generated=len(responses),
            verification_passed=verification_passed,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_answer(response: str) -> str:
        """
        Extract the "answer" from a response for self-consistency voting.

        Heuristics:
        1. Look for "The answer is..." / "Therefore..." / "In conclusion..."
        2. Extract final numerical result if present
        3. Fall back to last sentence
        """
        response_lower = response.lower()

        # Check for explicit answer markers
        answer_patterns = [
            r"(?:the answer is|therefore|thus|hence|so|in conclusion)[:\s]*(.*?)(?:\.|$)",
            r"(?:result|output|solution)[:\s]*(.*?)(?:\.|$)",
        ]
        for pattern in answer_patterns:
            match = re.search(pattern, response_lower, re.IGNORECASE)
            if match:
                return match.group(1).strip()[:200]

        # Check for final number (useful for math questions)
        numbers = re.findall(r'[\d,]+\.?\d*', response)
        if numbers:
            return numbers[-1]

        # Fallback: normalised last sentence
        sentences = re.split(r'[.!?]', response.strip())
        last_sentence = sentences[-1].strip() if sentences else response.strip()
        # Normalise whitespace for better comparison
        return " ".join(last_sentence.lower().split())[:200]


# Global singleton
_ttc_engine: Optional[TestTimeComputeEngine] = None


def get_ttc_engine() -> TestTimeComputeEngine:
    """Get the global test-time compute engine."""
    global _ttc_engine
    if _ttc_engine is None:
        _ttc_engine = TestTimeComputeEngine()
    return _ttc_engine
