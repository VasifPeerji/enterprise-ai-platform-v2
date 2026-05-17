@echo off
setlocal
REM Setup script for Enterprise AI Platform (Windows)
REM This script creates the conda environment and installs Poetry dependencies

echo Setting up Enterprise AI Platform...

where conda >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Conda is not installed. Please install Miniconda or Anaconda first.
    exit /b 1
)

echo Creating conda environment...
call conda env create -f environment.yml

if %ERRORLEVEL% NEQ 0 (
    echo Conda environment creation failed.
    echo If the environment already exists, run:
    echo   conda activate enterprise-ai-platform
    echo   poetry install
    exit /b 1
)

echo Installing Poetry dependencies in the conda environment...
call conda run -n enterprise-ai-platform poetry install

if %ERRORLEVEL% NEQ 0 (
    echo Poetry dependency installation failed.
    echo Try running these manually:
    echo   conda activate enterprise-ai-platform
    echo   poetry install
    exit /b 1
)

if not exist .env (
    copy .env.example .env >nul
    echo Created .env from .env.example
)

echo.
echo Installing ML dependencies for benchmark router...
call conda run -n enterprise-ai-platform pip install torch sentence-transformers scikit-learn joblib numpy --quiet

if %ERRORLEVEL% NEQ 0 (
    echo ML dependency installation failed. You can install manually:
    echo   pip install torch sentence-transformers scikit-learn joblib numpy
)

echo.
echo Setup complete.
echo Next steps:
echo   1. Start Ollama if you want local models
echo   2. Optionally start PostgreSQL, Redis, and Qdrant
echo   3. Run .\run.bat

pause
endlocal
