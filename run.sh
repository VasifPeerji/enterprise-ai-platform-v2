#!/bin/bash
# Quick start script for Enterprise AI Platform API

echo "🚀 Starting Enterprise AI Platform API..."

# Check if in conda environment
if [[ -z "${CONDA_DEFAULT_ENV}" ]]; then
    echo "⚠️  Conda environment not activated!"
    echo "Please run: conda activate enterprise-ai-platform"
    exit 1
fi

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found!"
    echo "Creating from .env.example..."
    cp .env.example .env
    echo "✅ .env created. Please edit it with your API keys."
    echo ""
fi

# Start the API server
echo "Starting server on http://localhost:8000"
echo ""
echo "📚 API Documentation: http://localhost:8000/docs"
echo "📘 ReDoc: http://localhost:8000/redoc"
echo "❤️  Health Check: http://localhost:8000/health"
echo ""
echo "Press Ctrl+C to stop"
echo ""

poetry run uvicorn src.interfaces.http.main:app --reload --host 0.0.0.0 --port 8000
