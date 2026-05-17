@echo off
setlocal

echo Starting Enterprise AI Platform...

if not exist .env (
    echo .env file not found. Copying from .env.example...
    copy .env.example .env >nul
    echo Created .env. Please update API keys and credentials if needed.
    echo.
)

echo Launching API on http://localhost:8000
echo API Docs: http://localhost:8000/docs
echo Health:   http://localhost:8000/health
echo Demo UI:  http://localhost:8000/chat/demo
echo Rag Citation: http://localhost:8000/rag-citations/demo
echo.

python -c "import uvicorn" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python -m uvicorn src.interfaces.http.main:app --reload --host 0.0.0.0 --port 8000
    goto :end
)

where poetry >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    poetry run uvicorn src.interfaces.http.main:app --reload --host 0.0.0.0 --port 8000
    goto :end
)

where conda >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Poetry was not found on PATH. Trying the enterprise-ai-platform conda environment...
    call conda run -n enterprise-ai-platform poetry run uvicorn src.interfaces.http.main:app --reload --host 0.0.0.0 --port 8000
    goto :end
)

echo Poetry is not available.
echo Install dependencies in the active environment, for example:
echo   pip install -r requirements.txt
echo Then run:
echo   .\run.bat
exit /b 1

:end
endlocal
