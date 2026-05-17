"""
Elite Routing Test Suite

Tests the 9-layer routing pipeline with various query types.
Run this to validate routing decisions and cost optimization.

Usage:
    python test_elite_routing.py
"""

import asyncio
import json
from typing import Any

import httpx

BASE_URL = "http://localhost:8000"

# Test cases organized by expected behavior
TEST_CASES = {
    "trivial": [
        "Hello",
        "Hi there",
        "Thanks",
        "Goodbye",
    ],
    "simple": [
        "What is 2+2?",
        "Who is the president?",
        "Define AI",
        "What's the capital of France?",
    ],
    "moderate": [
        "Explain how neural networks work",
        "What are the pros and cons of microservices?",
        "Compare Python and JavaScript",
        "How does blockchain technology work?",
    ],
    "complex": [
        "Analyze the time complexity of quicksort and explain why it's O(n log n) on average",
        "Compare the architectural tradeoffs between event-driven and request-response systems",
        "Explain quantum entanglement and its implications for computing",
        "Design a distributed caching system with high availability",
    ],
    "coding": [
        "Write a Python function to reverse a string",
        "Debug this code: for i in range(10) print(i)",
        "Implement a binary search tree in JavaScript",
        "Create a REST API endpoint in FastAPI",
    ],
    "creative": [
        "Write a short story about AI",
        "Generate ideas for a mobile app",
        "Create a poem about technology",
        "Brainstorm names for a startup",
    ],
}


class RoutingTester:
    """Test suite for elite routing validation."""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.results: list[dict[str, Any]] = []
    
    async def test_analyze_endpoint(self, query: str, expected_category: str) -> dict:
        """Test the /chat/analyze endpoint."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/analyze",
                    params={"message": query},
                    timeout=10.0,
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "query": query,
                        "expected_category": expected_category,
                        "status": "✅ PASS",
                        "selected_model": data["selected_model"]["name"],
                        "model_cost": data["selected_model"]["cost_per_1k"],
                        "intent": data["elite_pipeline_analysis"]["layer3_triage"]["intent"],
                        "complexity": data["elite_pipeline_analysis"]["layer3_triage"]["complexity_band"],
                        "confidence_level": data["elite_pipeline_analysis"]["confidence_level"],
                        "uncertainty": data["elite_pipeline_analysis"]["layer4_uncertainty"]["total_uncertainty"],
                        "escalation_available": data["escalation"]["available"],
                        "escalation_levels": data["escalation"]["levels"],
                    }
                else:
                    return {
                        "query": query,
                        "expected_category": expected_category,
                        "status": f"❌ FAIL (HTTP {response.status_code})",
                        "error": response.text,
                    }
            
            except Exception as e:
                return {
                    "query": query,
                    "expected_category": expected_category,
                    "status": f"❌ ERROR",
                    "error": str(e),
                }
    
    async def run_all_tests(self):
        """Run all test cases."""
        print("=" * 80)
        print("🧪 ELITE ROUTING VALIDATION TEST SUITE")
        print("=" * 80)
        print()
        
        total_tests = 0
        passed_tests = 0
        
        for category, queries in TEST_CASES.items():
            print(f"\n📊 Testing Category: {category.upper()}")
            print("-" * 80)
            
            for query in queries:
                total_tests += 1
                result = await self.test_analyze_endpoint(query, category)
                self.results.append(result)
                
                # Display result
                status = result.get("status", "UNKNOWN")
                if "✅" in status:
                    passed_tests += 1
                
                print(f"\n{status} Query: {query[:60]}...")
                
                if "✅" in status:
                    print(f"   Model: {result['selected_model']}")
                    print(f"   Intent: {result['intent']} | Complexity: {result['complexity']}")
                    print(f"   Confidence: {result['confidence_level']} | Uncertainty: {result['uncertainty']:.2f}")
                    print(f"   Cost/1K: ${result['model_cost']:.4f}")
                    print(f"   Escalation: {result['escalation_levels']} levels available")
                else:
                    print(f"   Error: {result.get('error', 'Unknown')}")
        
        # Summary
        print("\n" + "=" * 80)
        print("📈 TEST SUMMARY")
        print("=" * 80)
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests} ✅")
        print(f"Failed: {total_tests - passed_tests} ❌")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        # Cost Analysis
        self._analyze_costs()
        
        # Confidence Analysis
        self._analyze_confidence()
        
        # Model Distribution
        self._analyze_model_distribution()
    
    def _analyze_costs(self):
        """Analyze cost distribution."""
        print("\n" + "=" * 80)
        print("💰 COST ANALYSIS")
        print("=" * 80)
        
        free_models = sum(1 for r in self.results if r.get("model_cost", 1) == 0.0)
        paid_models = len(self.results) - free_models
        
        print(f"Free Models (Ollama): {free_models} ({free_models/len(self.results)*100:.1f}%)")
        print(f"Paid Models: {paid_models} ({paid_models/len(self.results)*100:.1f}%)")
        
        total_cost = sum(r.get("model_cost", 0) for r in self.results)
        print(f"Total Cost/1K tokens: ${total_cost:.4f}")
        print(f"Average Cost/1K tokens: ${total_cost/len(self.results):.4f}")
    
    def _analyze_confidence(self):
        """Analyze confidence distribution."""
        print("\n" + "=" * 80)
        print("🎯 CONFIDENCE ANALYSIS")
        print("=" * 80)
        
        high_conf = sum(1 for r in self.results if r.get("confidence_level") == "HIGH")
        med_conf = sum(1 for r in self.results if r.get("confidence_level") == "MEDIUM")
        low_conf = sum(1 for r in self.results if r.get("confidence_level") == "LOW")
        
        print(f"HIGH Confidence: {high_conf} ({high_conf/len(self.results)*100:.1f}%)")
        print(f"MEDIUM Confidence: {med_conf} ({med_conf/len(self.results)*100:.1f}%)")
        print(f"LOW Confidence: {low_conf} ({low_conf/len(self.results)*100:.1f}%)")
        
        avg_uncertainty = sum(r.get("uncertainty", 0) for r in self.results) / len(self.results)
        print(f"Average Uncertainty: {avg_uncertainty:.2f}")
    
    def _analyze_model_distribution(self):
        """Analyze model selection distribution."""
        print("\n" + "=" * 80)
        print("🤖 MODEL DISTRIBUTION")
        print("=" * 80)
        
        model_counts: dict[str, int] = {}
        for r in self.results:
            model = r.get("selected_model", "Unknown")
            model_counts[model] = model_counts.get(model, 0) + 1
        
        for model, count in sorted(model_counts.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / len(self.results)) * 100
            print(f"{model}: {count} ({percentage:.1f}%)")
    
    def save_results(self, filename: str = "routing_test_results.json"):
        """Save detailed results to JSON file."""
        with open(filename, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"\n💾 Detailed results saved to: {filename}")


async def main():
    """Run the test suite."""
    tester = RoutingTester()
    await tester.run_all_tests()
    tester.save_results()
    
    print("\n" + "=" * 80)
    print("✅ TEST SUITE COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Review routing_test_results.json for detailed analysis")
    print("2. Check if trivial/simple queries use free models")
    print("3. Verify complex queries use premium models")
    print("4. Validate confidence levels match complexity")


if __name__ == "__main__":
    asyncio.run(main())
