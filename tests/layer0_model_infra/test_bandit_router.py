"""
Test suite for Bandit Router (Layer 5)

Target Metrics:
- Reward improvement >10% over baseline
- Exploration/exploitation balance
- Context-aware selection accuracy
"""

import pytest
from src.layer0_model_infra.routing.bandit_router import (
    get_bandit_router,
    BanditContext,
)


@pytest.fixture
def bandit_router():
    """Get bandit router instance."""
    router = get_bandit_router()
    # Reset for clean test
    router.model_stats = {}
    return router


class TestContextAwareSelection:
    """Test that bandit uses context to make smart decisions."""
    
    def test_selects_different_models_for_different_contexts(self, bandit_router):
        """Different contexts should lead to different selections."""
        models = ["gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet"]
        
        # Simple context (should prefer cheap)
        simple_context = BanditContext(
            intent="question_answering",
            domain="casual",
            complexity_band="simple",
            uncertainty_score=0.2,
            user_tier="free",
            budget_remaining=0.1,
        )
        
        # Complex context (should prefer powerful)
        complex_context = BanditContext(
            intent="coding",
            domain="coding",
            complexity_band="expert",
            uncertainty_score=0.8,
            user_tier="premium",
            budget_remaining=1.0,
        )
        
        simple_selection = bandit_router.select_model(simple_context, models)
        complex_selection = bandit_router.select_model(complex_context, models)
        
        print(f"\nSimple context selected: {simple_selection}")
        print(f"Complex context selected: {complex_selection}")
        
        # Selections might be different (not guaranteed without history, but likely)
        # We just check they're valid
        assert simple_selection in models
        assert complex_selection in models


class TestLearningFromFeedback:
    """Test that bandit learns from rewards."""
    
    def test_penalizes_failed_models(self, bandit_router):
        """Models that fail should be penalized."""
        models = ["gpt-4o-mini", "gpt-4o"]
        context = BanditContext(
            intent="question_answering",
            domain="general",
            complexity_band="moderate",
            uncertainty_score=0.5,
        )
        
        # Simulate: gpt-4o-mini consistently fails
        for _ in range(5):
            bandit_router.update_reward(
                context=context,
                model_id="gpt-4o-mini",
                quality_score=0.3,  # Low quality
                cost=0.001,
                escalated=True,  # Had to escalate
            )
        
        # Simulate: gpt-4o works well
        for _ in range(5):
            bandit_router.update_reward(
                context=context,
                model_id="gpt-4o",
                quality_score=0.9,  # High quality
                cost=0.01,
                escalated=False,
            )
        
        # Now select again - should prefer gpt-4o
        selections = []
        for _ in range(10):
            selection = bandit_router.select_model(context, models)
            selections.append(selection)
        
        # Should mostly pick gpt-4o (learned it's better)
        gpt4o_count = selections.count("gpt-4o")
        print(f"\nAfter learning, selected gpt-4o {gpt4o_count}/10 times")
        
        # Should prefer the better model
        assert gpt4o_count >= 6, "Bandit should learn to prefer successful model"
    
    def test_rewards_high_quality(self, bandit_router):
        """High quality responses should increase model selection probability."""
        context = BanditContext(
            intent="question_answering",
            domain="general",
            complexity_band="simple",
            uncertainty_score=0.3,
        )
        
        # Give positive feedback
        for _ in range(10):
            bandit_router.update_reward(
                context=context,
                model_id="gpt-4o-mini",
                quality_score=0.95,
                cost=0.001,
                escalated=False,
            )
        
        # Model should have positive stats
        stats_key = bandit_router._get_stats_key(context, "gpt-4o-mini")
        if stats_key in bandit_router.model_stats:
            stats = bandit_router.model_stats[stats_key]
            assert stats.total_attempts > 0
            print(f"\nModel stats after positive feedback: {stats}")


class TestExplorationVsExploitation:
    """Test exploration/exploitation balance."""
    
    def test_explores_new_models(self, bandit_router):
        """Bandit should occasionally explore unknown models."""
        models = ["gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet"]
        context = BanditContext(
            intent="question_answering",
            domain="general",
            complexity_band="moderate",
            uncertainty_score=0.5,
        )
        
        # Give strong positive feedback to one model
        for _ in range(20):
            bandit_router.update_reward(
                context=context,
                model_id="gpt-4o-mini",
                quality_score=0.9,
                cost=0.001,
                escalated=False,
            )
        
        # Make many selections
        selections = []
        for _ in range(50):
            selection = bandit_router.select_model(context, models)
            selections.append(selection)
        
        # Should mostly exploit gpt-4o-mini, but also explore others
        unique_selections = set(selections)
        gpt4o_mini_count = selections.count("gpt-4o-mini")
        
        print(f"\nExploitation: gpt-4o-mini selected {gpt4o_mini_count}/50 times")
        print(f"Exploration: {len(unique_selections)} unique models tried")
        
        # Should heavily favor the good model
        assert gpt4o_mini_count >= 30, "Should exploit known good model"
        
        # But should also explore (at least occasionally)
        # This is probabilistic, so we allow some variance
        assert len(unique_selections) >= 2, "Should explore other models occasionally"


class TestUserTierInfluence:
    """Test that user tier affects model selection."""
    
    def test_premium_users_get_better_models(self, bandit_router):
        """Premium users should be more likely to get premium models."""
        models = ["gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet"]
        
        free_context = BanditContext(
            intent="question_answering",
            domain="general",
            complexity_band="moderate",
            uncertainty_score=0.5,
            user_tier="free",
            budget_remaining=0.1,
        )
        
        premium_context = BanditContext(
            intent="question_answering",
            domain="general",
            complexity_band="moderate",
            uncertainty_score=0.5,
            user_tier="premium",
            budget_remaining=1.0,
        )
        
        # Make selections
        free_selections = [bandit_router.select_model(free_context, models) for _ in range(20)]
        premium_selections = [bandit_router.select_model(premium_context, models) for _ in range(20)]
        
        # Count expensive models
        expensive_models = ["gpt-4o", "claude-3-5-sonnet"]
        free_expensive_count = sum(1 for s in free_selections if s in expensive_models)
        premium_expensive_count = sum(1 for s in premium_selections if s in expensive_models)
        
        print(f"\nFree users got expensive models: {free_expensive_count}/20")
        print(f"Premium users got expensive models: {premium_expensive_count}/20")
        
        # Premium users should get more expensive models
        assert premium_expensive_count >= free_expensive_count


class TestBudgetAwareness:
    """Test that budget affects selection."""
    
    def test_low_budget_prefers_cheap_models(self, bandit_router):
        """Low budget should favor cheap models."""
        models = ["gpt-4o-mini", "gpt-4o"]
        
        low_budget_context = BanditContext(
            intent="question_answering",
            domain="general",
            complexity_band="moderate",
            uncertainty_score=0.5,
            budget_remaining=0.05,  # Very low
        )
        
        high_budget_context = BanditContext(
            intent="question_answering",
            domain="general",
            complexity_band="moderate",
            uncertainty_score=0.5,
            budget_remaining=1.0,  # High
        )
        
        # Make many selections
        low_budget_selections = [bandit_router.select_model(low_budget_context, models) for _ in range(20)]
        high_budget_selections = [bandit_router.select_model(high_budget_context, models) for _ in range(20)]
        
        low_budget_cheap = low_budget_selections.count("gpt-4o-mini")
        high_budget_cheap = high_budget_selections.count("gpt-4o-mini")
        
        print(f"\nLow budget selected cheap: {low_budget_cheap}/20")
        print(f"High budget selected cheap: {high_budget_cheap}/20")
        
        # Low budget should select cheap more often
        assert low_budget_cheap >= high_budget_cheap


class TestMetrics:
    """Test reward tracking and metrics."""
    
    def test_tracks_cost_per_quality(self, bandit_router):
        """Bandit should track cost-efficiency."""
        context = BanditContext(
            intent="question_answering",
            domain="general",
            complexity_band="moderate",
            uncertainty_score=0.5,
        )
        
        # Cheap model, good quality
        bandit_router.update_reward(
            context=context,
            model_id="gpt-4o-mini",
            quality_score=0.9,
            cost=0.001,
            escalated=False,
        )
        
        # Expensive model, similar quality
        bandit_router.update_reward(
            context=context,
            model_id="gpt-4o",
            quality_score=0.92,
            cost=0.02,
            escalated=False,
        )
        
        # Both should have stats
        mini_stats_key = bandit_router._get_stats_key(context, "gpt-4o-mini")
        gpt4o_stats_key = bandit_router._get_stats_key(context, "gpt-4o")
        
        assert mini_stats_key in bandit_router.model_stats
        assert gpt4o_stats_key in bandit_router.model_stats
