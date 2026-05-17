# 🧪 Elite Routing Validation Checklist

This checklist helps you validate that the elite routing system is working correctly.

---

## ✅ Pre-Flight Checks

Before running tests, verify:

- [ ] Server is running (`./run.bat` or `./run.sh`)
- [ ] Server is accessible at http://localhost:8000
- [ ] PostgreSQL is running (`docker-compose ps`)
- [ ] At least one API key is configured in `.env` (OpenAI or Anthropic)
- [ ] No errors in server logs

---

## 🧪 Test Scenarios

### 1. Trivial Queries (Should use FREE Ollama models)

**Test:**
```bash
curl -X POST "http://localhost:8000/chat/analyze?message=Hello"
```

**Expected Results:**
- ✅ Model: `Phi-3 Mini (Ollama)` or similar free model
- ✅ Cost/1K: `$0.0000`
- ✅ Complexity: `trivial`
- ✅ Confidence Level: `HIGH`
- ✅ Uncertainty: `< 0.3`

**Why:** Trivial greetings don't need expensive models.

---

### 2. Simple Questions (Should use CHEAP models)

**Test:**
```bash
curl -X POST "http://localhost:8000/chat/analyze?message=What%20is%20the%20capital%20of%20France"
```

**Expected Results:**
- ✅ Model: Cheap model (Ollama or GPT-3.5)
- ✅ Cost/1K: `$0 - $0.002`
- ✅ Complexity: `simple`
- ✅ Intent: `informational` or `qa`
- ✅ Confidence Level: `HIGH` or `MEDIUM`

**Why:** Simple factual questions don't require premium reasoning.

---

### 3. Coding Tasks (Should use CODE-CAPABLE models)

**Test:**
```bash
curl -X POST "http://localhost:8000/chat/analyze?message=Write%20a%20Python%20function%20to%20reverse%20a%20string"
```

**Expected Results:**
- ✅ Model: Code-capable model
- ✅ Intent: `coding`
- ✅ Complexity: `moderate` or `complex`
- ✅ Modality includes high `code_weight`

**Why:** Coding requires specialized models.

---

### 4. Complex Reasoning (Should use PREMIUM models)

**Test:**
```bash
curl -X POST "http://localhost:8000/chat/analyze?message=Explain%20quantum%20entanglement%20and%20prove%20Bell%27s%20theorem"
```

**Expected Results:**
- ✅ Model: Premium model (GPT-4, Claude Sonnet/Opus)
- ✅ Cost/1K: `> $0.01`
- ✅ Complexity: `complex` or `expert`
- ✅ Confidence Level: `MEDIUM` or `LOW`
- ✅ Uncertainty: `> 0.5`

**Why:** Complex reasoning needs the best models.

---

## 📊 Validation Metrics

### Cost Optimization

Run full test suite:
```bash
python test_elite_routing.py
```

**Target Metrics:**
- ✅ `>60%` of queries use FREE models (Ollama)
- ✅ `<20%` of queries use premium models
- ✅ Average cost/1K tokens: `< $0.005`

**If metrics are off:**
- Too many premium models → Router is too conservative
- Too many free models → Router may miss complex queries

---

### Confidence Calibration

**Check:**
- ✅ Trivial/Simple → HIGH confidence (uncertainty < 0.3)
- ✅ Moderate → MEDIUM confidence (uncertainty 0.3-0.6)
- ✅ Complex → LOW confidence (uncertainty > 0.6)

**If calibration is off:**
- Adjust uncertainty thresholds in `uncertainty_estimator.py`

---

### Intent Detection

**Verify:**
- ✅ Greetings → `casual` intent
- ✅ Questions → `qa` or `informational` intent
- ✅ Code → `coding` intent
- ✅ Analysis → `analysis` intent

**If detection is poor:**
- Improve keyword lists in `fast_triage.py`
- (Future) Replace with actual LLM classifier

---

## 🔍 Common Issues & Fixes

### Issue: All queries use expensive models

**Symptom:** No Ollama models selected, everything uses GPT-4/Claude

**Fix:**
1. Check Ollama is installed and running: `ollama list`
2. Verify models are in registry: `curl http://localhost:8000/models | grep ollama`
3. Check routing config: Models should be sorted by cost (cheapest first)

---

### Issue: Routing decisions don't make sense

**Symptom:** Simple queries get complex models, or vice versa

**Fix:**
1. Check logs for routing reasoning
2. Verify uncertainty estimator is working
3. Check bandit warmup (needs ~50 samples to stabilize)

---

### Issue: Server errors on /chat/analyze

**Symptom:** 500 errors or exceptions

**Fix:**
1. Check server logs for detailed error
2. Verify all routing components initialized
3. Check database connection (if errors mention DB)

---

## 🎯 Success Criteria

Your elite routing is working correctly if:

✅ **Cost Optimization**
- Trivial queries are FREE (Ollama)
- Simple queries are cheap (<$0.002/1K)
- Only complex queries use premium models

✅ **Confidence Calibration**
- High confidence for simple queries
- Low confidence for complex/ambiguous queries

✅ **Intent Detection**
- Coding tasks detected correctly
- Creative vs analytical properly classified

✅ **Escalation Available**
- All queries have escalation paths (2-3 levels)
- Premium models at top of escalation chain

✅ **No Errors**
- All test queries return 200 OK
- No exceptions in server logs

---

## 📈 Next Steps After Validation

Once validation passes:

1. **Production Prep**
   - Add semantic memory caching (Layer 2)
   - Implement learning loop (Layer 9)
   - Set up monitoring dashboard

2. **Fine-Tuning**
   - Adjust uncertainty thresholds based on real data
   - Tune bandit exploration rate
   - Optimize cost/quality tradeoff

3. **Scale Testing**
   - Load test with 1000+ queries
   - Measure P95/P99 latency
   - Verify concurrent request handling

---

**Run tests now:**
```bash
# Quick validation (4 scenarios)
python quick_validate.py

# Full test suite (25+ scenarios)
python test_elite_routing.py
```
