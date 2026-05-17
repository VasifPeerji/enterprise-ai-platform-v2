#!/usr/bin/env python3
"""
Quick Elite Routing Validation

Fast sanity check to verify elite routing is working correctly.
Tests a few key scenarios and displays results.

Usage:
    python quick_validate.py
"""

import httpx

BASE_URL = "http://localhost:8000"


def test_query(query: str, description: str):
    """Test a single query and display results."""
    print(f"\n{'='*80}")
    print(f"📝 Test: {description}")
    print(f"Query: \"{query}\"")
    print("-" * 80)
    
    try:
        response = httpx.post(
            f"{BASE_URL}/chat/analyze",
            params={"message": query},
            timeout=10.0,
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract key info
            model = data["selected_model"]
            pipeline = data["elite_pipeline_analysis"]
            
            print(f"✅ Status: PASSED")
            print(f"\n🤖 Selected Model:")
            print(f"   • Name: {model['name']}")
            print(f"   • Provider: {model['provider']}")
            print(f"   • Cost/1K: ${model['cost_per_1k']:.4f}")
            
            print(f"\n🧠 Pipeline Analysis:")
            print(f"   • Modality: {pipeline['layer1_modality']['primary_modality']}")
            print(f"   • Intent: {pipeline['layer3_triage']['intent']}")
            print(f"   • Domain: {pipeline['layer3_triage']['domain']}")
            print(f"   • Complexity: {pipeline['layer3_triage']['complexity_band']}")
            
            print(f"\n📊 Confidence:")
            print(f"   • Level: {pipeline['confidence_level']}")
            print(f"   • Uncertainty: {pipeline['layer4_uncertainty']['total_uncertainty']:.2f}")
            
            print(f"\n🔄 Escalation:")
            print(f"   • Available: {data['escalation']['available']}")
            print(f"   • Levels: {data['escalation']['levels']}")
            
            print(f"\n💡 Routing Reasoning:")
            print(f"   {data['routing_reasoning']}")
            
            return True
        
        else:
            print(f"❌ Status: FAILED (HTTP {response.status_code})")
            print(f"Error: {response.text}")
            return False
    
    except Exception as e:
        print(f"❌ Status: ERROR")
        print(f"Exception: {str(e)}")
        return False


def main():
    """Run quick validation tests."""
    print("=" * 80)
    print("🚀 ELITE ROUTING - QUICK VALIDATION")
    print("=" * 80)
    print(f"Testing endpoint: {BASE_URL}")
    
    # Test 1: Trivial query (should use free model)
    test_query(
        "Hello",
        "Trivial Query (Should use FREE Ollama model)"
    )
    
    # Test 2: Simple question (should use cheap model)
    test_query(
        "What is the capital of France?",
        "Simple Question (Should use cheap model)"
    )
    
    # Test 3: Coding task (should use code-capable model)
    test_query(
        "Write a Python function to calculate fibonacci numbers",
        "Coding Task (Should use code-capable model)"
    )
    
    # Test 4: Complex reasoning (should use premium model)
    test_query(
        "Explain the time complexity of merge sort and provide a detailed proof with mathematical notation",
        "Complex Reasoning (Should use PREMIUM model)"
    )
    
    # Summary
    print("\n" + "=" * 80)
    print("✅ QUICK VALIDATION COMPLETE")
    print("=" * 80)
    print("\n📋 What to check:")
    print("   1. Trivial queries use FREE models (cost = $0)")
    print("   2. Simple queries use CHEAP models")
    print("   3. Complex queries use PREMIUM models")
    print("   4. Confidence levels match complexity (HIGH for simple, LOW for complex)")
    print("   5. Escalation paths are available")
    print("\n💡 Run full test suite with: python test_elite_routing.py")


if __name__ == "__main__":
    main()
