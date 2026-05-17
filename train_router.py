"""Train the benchmark router with full production parameters."""
from src.layer0_model_infra.routing.benchmark_router import BenchmarkRouter

r = BenchmarkRouter()
stats = r.train(n_estimators=200, max_depth=6)
print("Training complete:")
print(f"  Samples: {stats['training_samples']}")
print(f"  Classes: {stats['n_classes']}")
print(f"  Features: {stats['n_features']}")
print(f"  Accuracy: {stats['train_accuracy']}")
print(f"  Labels: {stats['class_labels']}")

# Quick verification
result = r.recommend("Hello", complexity_band="trivial")
print(f"\nVerification:")
print(f"  Trivial 'Hello' -> {result.recommended_model_id} ({result.tier}, method={result.method})")

result2 = r.recommend(
    "Prove convergence bounds for transformer attention",
    rubric={"task_count": 0.9, "domain_depth": 0.85, "reasoning_hops": 0.95,
            "output_structure": 0.8, "knowledge_breadth": 0.85, "raw_score": 0.9},
    complexity_band="expert",
)
print(f"  Expert 'Prove...' -> {result2.recommended_model_id} ({result2.tier}, quality={result2.quality_score})")
