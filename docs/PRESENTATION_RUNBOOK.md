# Presentation Runbook

This is the shortest, safest path to run the project for a live demo.

## Pre-requisites

- Conda environment `enterprise-ai-platform` already created
- `poetry install` already completed in that environment
- Docker Desktop running
- `.env` present in the repo root
- At least one working model path, with provider secrets set in OS environment variables:
  - `OPENAI_API_KEY`, or
  - `ANTHROPIC_API_KEY`, or
  - `GEMINI_API_KEY`, or
  - `GROQ_API_KEY`, or
  - `OPENROUTER_API_KEY`, or
  - Ollama running locally for local models

## Infrastructure

Start supporting services from the project root:

```powershell
docker-compose up -d
```

Optional local model runtime:

```powershell
ollama serve
```

Recommended local pulls:

```powershell
ollama pull qwen3:8b
ollama pull phi4-mini-reasoning:3.8b
ollama pull gemma3:4b
ollama pull llama3.1:8b
ollama pull deepseek-r1:7b
```

Optional free API setup for better quality than local-only demos:

- `GEMINI_API_KEY` for Gemini free tier
- `GROQ_API_KEY` for Groq free developer key
- `OPENROUTER_API_KEY` for OpenRouter free models/router
- `HUGGINGFACE_API_KEY` + `HUGGINGFACE_API_BASE` for an experimental Hugging Face inference path
- Keep these in OS environment variables, not in `.env`

When `PREFER_FREE_API_PROVIDERS=true`, the router will prefer configured free APIs and use Ollama as fallback.

## Start the App

From the repo root:

```powershell
run.bat
```

Equivalent manual command:

```powershell
poetry run uvicorn src.interfaces.http.main:app --reload --host 0.0.0.0 --port 8000
```

## What to Open

- Health: `http://localhost:8000/health`
- Ready: `http://localhost:8000/health/ready`
- Docs: `http://localhost:8000/docs`
- Demo UI: `http://localhost:8000/chat/demo`

## Live Demo Flow

1. Open `/health/ready` and show dependency status.
2. Open `/chat/demo`.
3. Start with `live routing` to show the real router output.
4. Switch to `demo simulation` to show free/local execution plus simulated commercial billing.
5. Run a simple query.
6. Run a coding query.
7. Run a hard cross-domain query.
8. Expand the JSON decision trail to show routing proof and simulation metadata.

## Suggested Queries

Simple:

```text
What is overfitting in machine learning?
```

Coding:

```text
Write a Python function for breadth-first search and explain its time complexity.
```

High-risk / reasoning:

```text
Compare the legal and ethical implications of using AI diagnosis tools in hospitals.
```

## Benchmark Evidence

Router-only benchmark:

```powershell
poetry run python scripts\presentation_benchmark.py --mode analyze
```

Full execution benchmark:

```powershell
poetry run python scripts\presentation_benchmark.py --mode execute
```

## Fast Troubleshooting

- If `/health/ready` shows database unhealthy:
  - confirm `docker-compose ps`
  - confirm `.env` DB values

- If model calls fail:
  - confirm API key exists in OS environment variables
  - or confirm Ollama is running

- If local free models are not selected:
  - check `/models`
  - confirm Ollama availability

- If you need a safe backup:
  - use `/chat/analyze` or the demo UI in analyze mode logic via the endpoint to show routing proof without depending on external model output

## Demo Simulation Mode

- `Execution Backend = demo simulation` keeps execution on local/free backing models.
- The UI separately shows the commercial tier being simulated and deducts from a mock wallet.
- Present this explicitly as simulated billing and simulated provider tier mapping.
- Do not claim a paid provider actually generated the response unless it really did.
