import json
data = json.load(open('src/layer0_model_infra/data/router_training_queries.json'))
for q in data['queries']:
    if q.get('labeling_method') == 'multi_llm_consensus' and q.get('complexity') != q.get('_original_complexity', q['complexity']):
        cs = q.get('consensus_scores', {})
        print(f"[{cs.get('raw_score',0):.3f}] {q['complexity']:8s} | {q['text'][:80]}")
    elif q.get('labeling_method') != 'multi_llm_consensus':
        pass  # skipped queries
