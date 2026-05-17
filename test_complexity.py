"""Direct test of complexity heuristic — no module imports that load models."""
import sys
import re

# Minimal reproduction of the heuristic logic
_MULTI_TECH_KEYWORDS = {
    "react", "angular", "vue", "next.js", "nextjs", "node",
    "django", "flask", "fastapi", "express", "spring",
    "docker", "kubernetes", "k8s", "terraform", "aws",
    "gcp", "azure", "redis", "postgres", "mongodb",
    "graphql", "rest api", "restful", "webpack",
    "typescript", "tailwind", "ci/cd", "cicd", "jenkins",
    "github actions", "pipeline", "deployment",
}

_COMPLEX_SYSTEM_PATTERNS = [
    "distributed system", "distributed consensus", "fault-tolerant",
    "multi-tenant", "event-driven architecture", "system design",
    "design an architecture", "ci/cd", "cicd", "pipeline",
    "microservice", "full-stack", "fullstack", "complete website",
    "complete application", "complete app", "entire application",
    "production-ready", "scalable", "load balancer",
    "end-to-end", "from scratch",
]

_SYSTEM_SIGNALS = (
    "complete ", "entire ", "full ", "end-to-end", "end to end",
    "from scratch", "production", "deploy",
)

_EXPERT_PATTERNS = [
    "riemann hypothesis", "formal proof", "proof of", "prove that",
    "prove the", "derive a new", "derive the mathematical",
    "completeness theorem", "np-hard", "computational complexity",
    "novel algorithm", "novel architecture", "convergence properties",
]

def is_multi_tech(query):
    tech_hits = sum(1 for kw in _MULTI_TECH_KEYWORDS if kw in query)
    if tech_hits >= 2:
        return True, f"2+ tech keywords ({tech_hits})"
    if tech_hits >= 1 and any(s in query for s in _SYSTEM_SIGNALS):
        return True, f"1 tech + system signal"
    if any(p in query for p in _COMPLEX_SYSTEM_PATTERNS):
        return True, f"complex system pattern"
    return False, f"tech_hits={tech_hits}"

def is_expert(query):
    if any(p in query for p in _EXPERT_PATTERNS):
        return True, [p for p in _EXPERT_PATTERNS if p in query]
    return False, []

queries = [
    "Build me a complete Education Website in Angular JS",
    "Build me a Education Website in Angular JS",
    "Prove the pythagoras theorem",
    "What is overfitting in machine learning?",
    "Write a Python function for breadth-first search",
    "Compare the legal and ethical implications of using AI diagnosis tools in hospitals.",
    "Design a distributed consensus protocol with formal safety proofs.",
]

for q in queries:
    ql = q.lower()
    mt, mt_reason = is_multi_tech(ql)
    ex, ex_patterns = is_expert(ql)
    print(f"Query: {q}")
    print(f"  multi_tech={mt} ({mt_reason})")
    print(f"  expert={ex} {ex_patterns}")
    print()
