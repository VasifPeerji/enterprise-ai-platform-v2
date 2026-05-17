"""
Verification Script for Elite Routing Loop
Simulates the full "Brain + Body" pipeline.
"""
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.layer2_orchestrator.execution_loop import get_orchestrator
from src.layer0_model_infra.models import ModelDefinition
from src.layer0_model_infra.registry import get_registry

# Mocking the Gateway to control responses
from unittest.mock import AsyncMock, MagicMock
from src.layer0_model_infra import gateway

async def verify_loop():
    print("🚀 Starting Elite Loop Verification...")
    
    orchestrator = get_orchestrator()
    registry = get_registry()
    
    # 1. SETUP MOCKS
    # We want to simulate: 
    # - Router picks "Cheap Model" (e.g. gpt-4o-mini)
    # - Gateway returns "Bad Answer" for Cheap Model
    # - Quality Check Fails
    # - Orchestrator Escalates to "Expensive Model" (e.g. gpt-4o)
    # - Gateway returns "Good Answer"
    # - Quality Check Passes
    
    # Mock Gateway
    mock_gateway = AsyncMock()
    
    async def mock_complete(request):
        model_id = request.model_id
        print(f"   --> Gateway called with: {model_id}")
        
        # Simulate Cheap Model Failure
        if "mini" in model_id or "flash" in model_id:
            return MagicMock(
                content="I don't know.", 
                model_id=model_id,
                cost_usd=0.0001
            )
        # Simulate Expensive Model Success
        else:
            return MagicMock(
                content="The answer is 42, calculated by Deep Thought.", 
                model_id=model_id,
                cost_usd=0.01
            )
            
    mock_gateway.complete.side_effect = mock_complete
    orchestrator.gateway = mock_gateway
    
    # Mock Quality Evaluator to be deterministic
    orchestrator.quality_evaluator.evaluate = MagicMock()
    def mock_eval(response, query, model_id):
        if response == "I don't know.":
            return MagicMock(overall_quality=0.1, passes_threshold=False, reasoning="Too short")
        else:
            return MagicMock(overall_quality=0.9, passes_threshold=True, reasoning="Good answer")
    orchestrator.quality_evaluator.evaluate.side_effect = mock_eval

    # Mock Bandit (we just want to see if update_reward is called)
    orchestrator.bandit.update_reward = MagicMock()
    
    # 2. RUN EXECUTION
    print("\n📝 Executing Query: 'Explain quantum entanglement'")
    result = await orchestrator.execute(
        query="Explain quantum entanglement",
        user_tier="premium", # Rich context
        budget_remaining=10.0
    )
    
    # 3. VERIFY RESULTS
    print("\n🔍 Verification Results:")
    print(f"Content: {result.content}")
    print(f"Final Model: {result.model_used}")
    print(f"Escalation Count: {result.escalation_count}")
    print(f"Total Cost: ${result.total_cost_usd}")
    
    # Assertions
    assert result.escalation_count > 0, "❌ Failed to escalate!"
    assert "The answer is 42" in result.content, "❌ Failed to get good answer!"
    
    # Verify Bandit Feedback
    # Should have 2 calls: 1 penalty (cheap), 1 reward (expensive)
    assert orchestrator.bandit.update_reward.call_count >= 2, "❌ Bandit not updated correctly!"
    
    print("\n✅ SUCCESS: Elite Loop Verified!")
    print(" - Router selected cheap model first")
    print(" - Quality check caught failure")
    print(" - Orchestrator escalated to better model")
    print(" - Bandit received feedback (Penalty + Reward)")

if __name__ == "__main__":
    asyncio.run(verify_loop())
