"""
📁 File: src/layer0_model_infra/routing/input_signals.py
Layer: Layer 0 - Routing (Feature Extraction)
Purpose: Extract raw difficulty signals from input
Depends on: None
Used by: Bandit, uncertainty estimator, quality thresholds

Extracts comprehensive features that indicate query difficulty:
- Length, structure, complexity indicators
- Task type classification
- Reasoning depth analysis
- Output format detection
- These feed into downstream components
"""

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.shared.logger import get_logger

logger = get_logger(__name__)


class TaskType(str, Enum):
    """Detected task type from input."""
    QA = "qa"
    GENERATION = "generation"
    TRANSFORMATION = "transformation"
    ANALYSIS = "analysis"
    CONVERSATION = "conversation"


class RequiredFormat(str, Enum):
    """Detected output format requested."""
    PROSE = "prose"
    JSON = "json"
    TABLE = "table"
    CODE = "code"
    LIST = "list"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


class InputSignals(BaseModel):
    """Raw signals extracted from input."""

    # Length signals
    char_count: int = Field(..., description="Character count")
    word_count: int = Field(..., description="Word count")
    sentence_count: int = Field(..., description="Sentence count")
    prompt_length: int = Field(default=0, description="Raw prompt byte length")

    # Structure signals
    question_count: int = Field(..., description="Number of questions")
    has_code_blocks: bool = Field(..., description="Contains code blocks")
    code_block_count: int = Field(default=0, description="Number of code blocks")
    has_lists: bool = Field(..., description="Contains bullet/numbered lists")

    # Format requests
    requests_json: bool = Field(..., description="Asks for JSON output")
    requests_table: bool = Field(..., description="Asks for table format")
    requests_code: bool = Field(..., description="Asks for code")
    requests_detailed: bool = Field(..., description="Asks for detailed response")
    required_format: RequiredFormat = Field(
        default=RequiredFormat.UNKNOWN, description="Detected output format"
    )

    # Complexity indicators
    has_technical_terms: bool = Field(..., description="Contains technical jargon")
    has_multi_part: bool = Field(..., description="Multi-part question")
    has_constraints: bool = Field(..., description="Has explicit constraints")

    # ── New fields ─────────────────────────────────────────────────────────
    task_type: TaskType = Field(
        default=TaskType.QA, description="Classified task type"
    )
    instruction_count: int = Field(
        default=1, description="Number of distinct instructions"
    )
    context_length: int = Field(
        default=0, description="Estimated context tokens needed"
    )
    multi_intent_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Multi-intent likelihood (0-1)"
    )
    reasoning_depth: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Reasoning chain depth (0-1)"
    )
    numerical_reasoning_flag: bool = Field(
        default=False, description="Math / numerical computation present"
    )
    code_generation_flag: bool = Field(
        default=False, description="Explicitly requests code output"
    )

    # Computed scores
    length_score: float = Field(..., ge=0.0, le=1.0, description="Length complexity (0-1)")
    structure_score: float = Field(..., ge=0.0, le=1.0, description="Structure complexity (0-1)")
    overall_difficulty: float = Field(..., ge=0.0, le=1.0, description="Overall difficulty (0-1)")


class InputSignalExtractor:
    """
    Extract raw difficulty signals from input.

    These become features for:
    - Bandit context
    - Uncertainty estimation
    - Quality thresholds
    - TTC strategy selection
    """

    # Technical term indicators
    TECHNICAL_PATTERNS = [
        r'\b[A-Z]{2,}\b',                 # Acronyms
        r'\b(?:algorithm|complexity|architecture|implementation|optimization)\b',
        r'\b(?:async|await|promise|callback|thread|mutex)\b',
        r'\b(?:O\(\w+\))',                # Big-O notation
        r'\b(?:API|SDK|REST|GraphQL|gRPC|HTTP|SQL|NoSQL|BFS|DFS|Dijkstra)\b',
        r'\b(?:latency|throughput|scalability|concurrency)\b',
        r'\b(?:python|java|javascript|c\+\+|typescript|react|node)\b',
    ]

    # Constraint indicators
    CONSTRAINT_KEYWORDS = [
        "must", "should", "need to", "required", "constraint",
        "without", "except", "but not", "only", "exactly",
        "no more than", "at least", "at most", "between",
        "limited to", "restricted to", "cannot", "forbidden",
    ]

    # Instruction delimiters
    INSTRUCTION_DELIMITERS = [
        r'\d+\.\s+',                                  # "1. Do this"
        r'(?:first|second|third|then|next|finally|lastly)',  # sequence words
        r'(?:step\s+\d+)',                            # "Step 1"
        r'\n\s*[-*•]\s+',                             # bullet points
    ]

    # Reasoning depth indicators (causal chains, conditionals, comparisons)
    REASONING_PATTERNS = [
        (r'\bif\b.*\bthen\b', 0.2),
        (r'\bbecause\b|\bsince\b|\btherefore\b|\bthus\b', 0.15),
        (r'\bcompare\b|\bcontrast\b|\bdifference\b|\bsimilar\b', 0.15),
        (r'\bwhy\b.*\b(does|is|was|would|should)\b', 0.15),
        (r'\bprove\b|\bderive\b|\bdemonstrate\b', 0.25),
        (r'\banalyze\b|\bevaluate\b|\bassess\b|\bcritique\b', 0.15),
        (r'\btrade-?off\b|\bpros?\s+and\s+cons?\b|\badvantage\b', 0.1),
        (r'\bhowever\b|\balthough\b|\bnevertheless\b|\bdespite\b', 0.1),
    ]

    # Numerical reasoning patterns
    NUMERICAL_PATTERNS = [
        r'\b\d+\s*[\+\-\*\/\%\^]\s*\d+',       # arithmetic
        r'\bcalculate\b|\bcompute\b|\bsolve\b',
        r'\bhow\s+many\b|\bhow\s+much\b',
        r'\bpercentage\b|\bratio\b|\bproportion\b',
        r'\bequation\b|\bformula\b|\bderivative\b|\bintegral\b',
        r'\bstatistic\b|\bmean\b|\bmedian\b|\bvariance\b|\bstandard\s+deviation\b',
        r'\belectric\s+field\b|\bcharge\b|\bcoulomb\b|\bvoltage\b|\bcurrent\b',
        r'\bdistance\b.*\bcharge\b|\bmeters?\b|\bnewtons?\b|\bμc\b|\buc\b',
    ]

    # Code generation keywords
    CODE_GEN_KEYWORDS = [
        "write a function", "write code", "implement", "create a script",
        "write a program", "code that", "build a", "develop a",
        "write a class", "create a method", "generate code",
        "debug", "fix this bug", "sql query", "write a sql query",
        "api client", "rest api", "reverse a linked list",
        "binary search", "breadth-first search", "bfs", "dfs", "dijkstra",
        "need code", "code to", "longest substring",
    ]

    # Multi-intent connectors (stronger signal than simple "and")
    MULTI_INTENT_CONNECTORS = [
        "and also", "but also", "additionally", "moreover", "furthermore",
        "on top of that", "in addition", "as well as", "plus",
    ]

    # Task type keywords
    TASK_TYPE_INDICATORS = {
        TaskType.GENERATION: [
            "write", "create", "generate", "compose", "draft",
            "produce", "make", "design", "build",
        ],
        TaskType.TRANSFORMATION: [
            "convert", "transform", "translate", "rewrite", "refactor",
            "restructure", "format", "paraphrase", "summarize",
        ],
        TaskType.ANALYSIS: [
            "analyze", "evaluate", "assess", "review", "examine",
            "investigate", "break down", "dissect", "critique",
        ],
        TaskType.CONVERSATION: [
            "hello", "hi", "hey", "thanks", "bye", "chat",
            "how are you", "what's up",
        ],
    }

    def extract(self, query: str) -> InputSignals:
        """
        Extract all signals from query.

        Args:
            query: User's query

        Returns:
            Input signals with comprehensive difficulty features
        """
        query_lower = query.lower()

        # ── Length signals ─────────────────────────────────────────────────
        char_count = len(query)
        word_count = len(query.split())
        sentence_count = max(
            query.count('.') + query.count('?') + query.count('!'), 1
        )
        prompt_length = len(query.encode("utf-8"))

        # ── Structure signals ──────────────────────────────────────────────
        question_count = query.count('?')
        code_block_count = len(re.findall(r'```[\s\S]*?```', query))
        has_code_blocks = code_block_count > 0
        has_lists = bool(
            re.search(r'[\n\r][\s]*[-*•]\s', query) or
            re.search(r'[\n\r][\s]*\d+\.\s', query)
        )

        # ── Format requests ────────────────────────────────────────────────
        requests_json = any(kw in query_lower for kw in ["json", "as json", "in json", "json format"])
        requests_table = any(kw in query_lower for kw in ["table", "tabular", "as table", "table format"])
        requests_code = any(
            kw in query_lower
            for kw in ["write code", "implement", "function", "script", "need code", "code to"]
        )
        requests_detailed = any(kw in query_lower for kw in [
            "detailed", "in detail", "comprehensive", "thorough",
            "step by step", "explain", "elaborate"
        ])

        # ── Required output format ─────────────────────────────────────────
        required_format = self._detect_required_format(query_lower)

        # ── Complexity indicators ──────────────────────────────────────────
        has_technical_terms = any(
            re.search(pattern, query, re.IGNORECASE)
            for pattern in self.TECHNICAL_PATTERNS
        )
        has_constraints = any(kw in query_lower for kw in self.CONSTRAINT_KEYWORDS)

        # ── Instruction count ──────────────────────────────────────────────
        instruction_count = self._count_instructions(query, query_lower)

        # ── Multi-intent score (continuous 0-1) ────────────────────────────
        multi_intent_score = self._compute_multi_intent_score(query_lower, question_count, instruction_count)
        has_multi_part = multi_intent_score > 0.3

        # ── Task type ──────────────────────────────────────────────────────
        task_type = self._classify_task_type(query_lower)

        # ── Context length estimate ────────────────────────────────────────
        context_length = self._estimate_context_length(query, has_code_blocks, code_block_count)

        # ── Reasoning depth ────────────────────────────────────────────────
        reasoning_depth = self._compute_reasoning_depth(query_lower)

        # ── Numerical reasoning ────────────────────────────────────────────
        numerical_reasoning_flag = any(
            re.search(p, query_lower) for p in self.NUMERICAL_PATTERNS
        )

        # ── Code generation flag ───────────────────────────────────────────
        code_generation_flag = any(kw in query_lower for kw in self.CODE_GEN_KEYWORDS)

        # ── Computed scores ────────────────────────────────────────────────
        length_score = self._compute_length_score(char_count, word_count)
        structure_score = self._compute_structure_score(
            question_count, has_code_blocks, has_lists, has_multi_part,
            instruction_count, has_constraints,
        )

        # Overall difficulty (weighted average with new signals)
        overall_difficulty = (
            length_score * 0.15
            + structure_score * 0.15
            + (1.0 if has_technical_terms else 0.0) * 0.10
            + (1.0 if has_constraints else 0.0) * 0.10
            + multi_intent_score * 0.10
            + reasoning_depth * 0.15
            + (1.0 if numerical_reasoning_flag else 0.0) * 0.10
            + (1.0 if code_generation_flag else 0.0) * 0.05
            + min(instruction_count / 5.0, 1.0) * 0.10
        )

        signals = InputSignals(
            char_count=char_count,
            word_count=word_count,
            sentence_count=sentence_count,
            prompt_length=prompt_length,
            question_count=question_count,
            has_code_blocks=has_code_blocks,
            code_block_count=code_block_count,
            has_lists=has_lists,
            requests_json=requests_json,
            requests_table=requests_table,
            requests_code=requests_code,
            requests_detailed=requests_detailed,
            required_format=required_format,
            has_technical_terms=has_technical_terms,
            has_multi_part=has_multi_part,
            has_constraints=has_constraints,
            task_type=task_type,
            instruction_count=instruction_count,
            context_length=context_length,
            multi_intent_score=multi_intent_score,
            reasoning_depth=reasoning_depth,
            numerical_reasoning_flag=numerical_reasoning_flag,
            code_generation_flag=code_generation_flag,
            length_score=length_score,
            structure_score=structure_score,
            overall_difficulty=round(overall_difficulty, 4),
        )

        logger.debug(
            "input_signals_extracted",
            word_count=word_count,
            difficulty=overall_difficulty,
            task_type=task_type.value,
            reasoning_depth=reasoning_depth,
            multi_intent=multi_intent_score,
            instructions=instruction_count,
        )

        return signals

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_required_format(self, query: str) -> RequiredFormat:
        """Detect what output format is requested."""
        if any(kw in query for kw in ["json", "as json", "json format", "json object"]):
            return RequiredFormat.JSON
        if any(kw in query for kw in ["table", "tabular", "as table", "csv"]):
            return RequiredFormat.TABLE
        if any(kw in query for kw in [
            "write code", "implement", "function", "script", "code for",
            "write a program", "class that", "need code", "code to",
        ]):
            return RequiredFormat.CODE
        if any(kw in query for kw in ["list", "bullet", "enumerate", "itemize"]):
            return RequiredFormat.LIST
        if any(kw in query for kw in ["markdown", "md format"]):
            return RequiredFormat.MARKDOWN
        return RequiredFormat.UNKNOWN

    def _count_instructions(self, query: str, query_lower: str) -> int:
        """Count distinct instructions in a query."""
        count = 0
        for pattern in self.INSTRUCTION_DELIMITERS:
            count += len(re.findall(pattern, query_lower))

        # Also count imperative verbs at line starts
        lines = query.strip().split('\n')
        imperative_verbs = {
            "write", "create", "list", "explain", "describe", "show",
            "find", "calculate", "compare", "analyze", "generate",
            "build", "implement", "design", "convert", "translate",
        }
        for line in lines:
            first_word = line.strip().split()[0].lower() if line.strip() else ""
            if first_word in imperative_verbs:
                count += 1

        return max(count, 1)  # at least 1 instruction

    def _compute_multi_intent_score(
        self, query: str, question_count: int, instruction_count: int
    ) -> float:
        """Compute continuous multi-intent score (0-1)."""
        score = 0.0

        # Multiple questions
        if question_count >= 2:
            score += 0.3
        if question_count >= 4:
            score += 0.2

        # Multi-intent connectors
        connector_hits = sum(1 for c in self.MULTI_INTENT_CONNECTORS if c in query)
        score += min(connector_hits * 0.2, 0.4)

        # Sequential directives often indicate a multi-part task even without multiple questions.
        sequence_hits = sum(
            1 for marker in ["first", "then", "next", "finally", "after that"]
            if marker in query
        )
        if sequence_hits >= 2:
            score += 0.25

        # Multiple instructions
        if instruction_count >= 3:
            score += 0.2
        if instruction_count >= 5:
            score += 0.1

        return min(score, 1.0)

    def _classify_task_type(self, query: str) -> TaskType:
        """Classify the primary task type."""
        scores: dict[TaskType, int] = {}
        for ttype, keywords in self.TASK_TYPE_INDICATORS.items():
            score = sum(1 for kw in keywords if kw in query)
            if score > 0:
                scores[ttype] = score

        if not scores:
            return TaskType.QA  # Default

        return max(scores, key=scores.get)

    def _estimate_context_length(
        self, query: str, has_code: bool, code_block_count: int
    ) -> int:
        """Estimate how many context tokens the query needs."""
        base = len(query) // 4  # query tokens

        # Code blocks need more context
        if has_code:
            base += code_block_count * 200

        # Estimate output tokens needed (rough)
        if len(query) < 50:
            output_estimate = 100
        elif len(query) < 200:
            output_estimate = 500
        else:
            output_estimate = 1500

        return base + output_estimate

    def _compute_reasoning_depth(self, query: str) -> float:
        """Compute reasoning chain depth (0-1)."""
        depth = 0.0
        for pattern, weight in self.REASONING_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                depth += weight
        return min(depth, 1.0)

    def _compute_length_score(self, char_count: int, word_count: int) -> float:
        """Compute length-based complexity score (0-1)."""
        if word_count < 10:
            return 0.1
        elif word_count < 30:
            return 0.3
        elif word_count < 100:
            return 0.5
        elif word_count < 200:
            return 0.7
        elif word_count < 500:
            return 0.85
        else:
            return 0.95

    def _compute_structure_score(
        self,
        question_count: int,
        has_code_blocks: bool,
        has_lists: bool,
        has_multi_part: bool,
        instruction_count: int = 1,
        has_constraints: bool = False,
    ) -> float:
        """Compute structure-based complexity score (0-1)."""
        score = 0.0

        if question_count > 1:
            score += 0.2
        if has_code_blocks:
            score += 0.2
        if has_lists:
            score += 0.15
        if has_multi_part:
            score += 0.15
        if instruction_count >= 3:
            score += 0.15
        if has_constraints:
            score += 0.15

        return min(score, 1.0)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_extractor: Optional[InputSignalExtractor] = None


def get_input_extractor() -> InputSignalExtractor:
    """Get global input signal extractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = InputSignalExtractor()
    return _extractor
