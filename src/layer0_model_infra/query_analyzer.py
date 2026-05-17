"""
📁 File: src/layer0_model_infra/query_analyzer.py
Layer: Layer 0 (Model Infrastructure)
Purpose: Analyze queries to determine optimal model selection
Depends on: pydantic
Used by: Model router

Analyzes:
- Query complexity (simple, moderate, complex)
- Modality (text, image, audio, multimodal)
- Intent type (informational, transactional, creative)
- Token estimation
"""

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.shared.logger import get_logger
from src.layer0_model_infra.routing.complexity_classifier import get_complexity_classifier

logger = get_logger(__name__)


class QueryComplexity(str, Enum):
    """Complexity levels for queries."""
    
    SIMPLE = "simple"  # FAQ, greetings, basic info
    MODERATE = "moderate"  # Standard reasoning, multi-step
    COMPLEX = "complex"  # Advanced reasoning, coding, research


class QueryModality(str, Enum):
    """Input modality types."""
    
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    MULTIMODAL = "multimodal"


class QueryIntent(str, Enum):
    """High-level intent categories."""
    
    INFORMATIONAL = "informational"  # Questions, lookups
    CONVERSATIONAL = "conversational"  # Chat, greetings
    ANALYTICAL = "analytical"  # Analysis, reasoning
    CREATIVE = "creative"  # Writing, brainstorming
    TECHNICAL = "technical"  # Coding, debugging
    TRANSACTIONAL = "transactional"  # Actions, commands


class QueryAnalysis(BaseModel):
    """Results of query analysis."""
    
    complexity: QueryComplexity = Field(..., description="Query complexity level")
    modality: QueryModality = Field(..., description="Input modality")
    intent: QueryIntent = Field(..., description="High-level intent")
    estimated_tokens: int = Field(..., description="Estimated token count")
    requires_reasoning: bool = Field(..., description="Requires advanced reasoning")
    requires_creativity: bool = Field(..., description="Requires creative generation")
    requires_coding: bool = Field(..., description="Involves code")
    reasoning_score: float = Field(
        ..., ge=0.0, le=1.0, description="Reasoning requirement score"
    )


class QueryAnalyzer:
    """
    Analyzes queries to determine optimal model routing.
    
    This analyzer uses heuristics for intent/modality and delegates
    complexity to the LLM-based ComplexityClassifier.
    """

    def __init__(self) -> None:
        self._complexity_classifier = get_complexity_classifier()
    
    # Keywords indicating complexity
    SIMPLE_KEYWORDS = {
        "hello", "hi", "hey", "thanks", "thank you", "bye", "yes", "no",
        "what is", "who is", "when is", "where is", "define",
    }
    
    COMPLEX_KEYWORDS = {
        "analyze", "compare", "evaluate", "explain why", "reasoning",
        "strategy", "optimize", "design", "architecture", "algorithm",
        "prove", "derive", "calculate", "solve",
    }
    
    TECHNICAL_KEYWORDS = {
        "code", "function", "class", "debug", "error", "bug", "implement",
        "python", "javascript", "java", "api", "sql", "database",
        "refactor", "test", "deploy",
    }
    
    CREATIVE_KEYWORDS = {
        "write", "story", "poem", "creative", "imagine", "generate",
        "brainstorm", "idea", "design", "compose", "draft",
    }

    CONSTRAINT_KEYWORDS = {
        "must", "should", "need to", "without", "only", "exactly",
        "at least", "at most", "cannot", "required",
    }

    REASONING_INDICATORS = {
        "if", "then", "because", "since", "therefore", "however",
        "although", "but", "yet", "nevertheless", "compare",
        "analyze", "evaluate", "tradeoff", "trade-off",
    }
    
    def analyze(
        self,
        query: str,
        has_images: bool = False,
        has_audio: bool = False,
    ) -> QueryAnalysis:
        """
        Analyze a query to determine routing requirements.
        
        Args:
            query: User's query text
            has_images: Whether images are attached
            has_audio: Whether audio is attached
            
        Returns:
            Query analysis with routing recommendations
        """
        query_lower = query.lower()
        
        # Determine modality
        modality = self._determine_modality(has_images, has_audio)
        
        # Determine intent
        intent = self._determine_intent(query_lower)
        
        # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
        estimated_tokens = len(query) // 4
        
        # Determine complexity
        complexity = self._determine_complexity(query_lower, estimated_tokens)
        
        # Check capability requirements
        requires_coding = self._requires_coding(query_lower)
        requires_creativity = self._requires_creativity(query_lower)
        requires_reasoning = self._requires_reasoning(query_lower, complexity)
        
        # Calculate reasoning score (0-1)
        reasoning_score = self._calculate_reasoning_score(
            query_lower, complexity, requires_reasoning
        )
        
        analysis = QueryAnalysis(
            complexity=complexity,
            modality=modality,
            intent=intent,
            estimated_tokens=estimated_tokens,
            requires_reasoning=requires_reasoning,
            requires_creativity=requires_creativity,
            requires_coding=requires_coding,
            reasoning_score=reasoning_score,
        )
        
        logger.debug(
            "query_analyzed",
            complexity=complexity,
            modality=modality,
            intent=intent,
            reasoning_score=reasoning_score,
        )
        
        return analysis
    
    def _determine_modality(
        self, has_images: bool, has_audio: bool
    ) -> QueryModality:
        """Determine input modality."""
        if has_images and has_audio:
            return QueryModality.MULTIMODAL
        elif has_images:
            return QueryModality.IMAGE
        elif has_audio:
            return QueryModality.AUDIO
        else:
            return QueryModality.TEXT
    
    def _determine_intent(self, query_lower: str) -> QueryIntent:
        """Determine high-level intent."""
        # Check for technical/coding
        if any(kw in query_lower for kw in self.TECHNICAL_KEYWORDS):
            return QueryIntent.TECHNICAL
        
        # Check for creative
        if any(kw in query_lower for kw in self.CREATIVE_KEYWORDS):
            return QueryIntent.CREATIVE
        
        # Check for analytical
        if any(kw in query_lower for kw in self.COMPLEX_KEYWORDS):
            return QueryIntent.ANALYTICAL
        
        # Check for conversational (greetings, simple responses)
        if any(kw in query_lower for kw in self.SIMPLE_KEYWORDS):
            return QueryIntent.CONVERSATIONAL
        
        # Check for questions (informational)
        if query_lower.startswith(("what", "who", "when", "where", "why", "how")):
            return QueryIntent.INFORMATIONAL
        
        # Default to informational
        return QueryIntent.INFORMATIONAL
    
    def _determine_complexity(
        self, query_lower: str, estimated_tokens: int
    ) -> QueryComplexity:
        """Determine query complexity via LLM-based classifier."""
        result = self._complexity_classifier.classify(query_lower)
        band = result.complexity_band

        # Map 5-band to 3-level enum
        if band in {"trivial", "simple"}:
            return QueryComplexity.SIMPLE
        if band == "moderate":
            return QueryComplexity.MODERATE
        # complex, expert
        return QueryComplexity.COMPLEX
    
    def _requires_coding(self, query_lower: str) -> bool:
        """Check if query involves coding."""
        return any(kw in query_lower for kw in self.TECHNICAL_KEYWORDS)
    
    def _requires_creativity(self, query_lower: str) -> bool:
        """Check if query requires creativity."""
        return any(kw in query_lower for kw in self.CREATIVE_KEYWORDS)
    
    def _requires_reasoning(
        self, query_lower: str, complexity: QueryComplexity
    ) -> bool:
        """Check if query requires advanced reasoning."""
        if complexity == QueryComplexity.COMPLEX:
            return True
        
        reasoning_patterns = [
            "why", "explain", "compare", "analyze", "evaluate",
            "reasoning", "logic", "proof", "derive",
        ]
        
        return any(pattern in query_lower for pattern in reasoning_patterns)
    
    def _calculate_reasoning_score(
        self,
        query_lower: str,
        complexity: QueryComplexity,
        requires_reasoning: bool,
    ) -> float:
        """
        Calculate a reasoning requirement score (0-1).
        
        This helps the router make fine-grained decisions.
        """
        score = 0.0
        
        # Base score from complexity
        if complexity == QueryComplexity.SIMPLE:
            score = 0.2
        elif complexity == QueryComplexity.MODERATE:
            score = 0.5
        else:  # COMPLEX
            score = 0.8
        
        # Boost for reasoning indicators
        if requires_reasoning:
            score += 0.15
        
        # Boost for specific reasoning keywords
        advanced_reasoning = [
            "prove", "derive", "theorem", "logic", "deduce", "infer",
            "strategy", "optimize", "algorithm",
        ]
        if any(kw in query_lower for kw in advanced_reasoning):
            score += 0.15
        
        # Boost for multi-step reasoning
        step_indicators = ["first", "then", "next", "finally", "step"]
        if sum(kw in query_lower for kw in step_indicators) >= 2:
            score += 0.1
        
        # Cap at 1.0
        return min(score, 1.0)


# Global analyzer instance
_analyzer: Optional[QueryAnalyzer] = None


def get_analyzer() -> QueryAnalyzer:
    """
    Get the global query analyzer instance.
    
    Returns:
        Query analyzer singleton
    """
    global _analyzer
    if _analyzer is None:
        _analyzer = QueryAnalyzer()
    return _analyzer
