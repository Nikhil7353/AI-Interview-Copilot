# Build a Windows folder for AI Interview Copilot.
# Output: dist\AIInterviewCopilot\AIInterviewCopilot.exe
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
& $python -m pip install "pyinstaller>=6,<7"
& $python -m PyInstaller --noconfirm --windowed --name AIInterviewCopilot `
    --icon "app\assets\app-icon.ico" `
    --add-data "app\assets;assets" `
    --paths . `
    --collect-submodules app `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtGui `
    --hidden-import PySide6.QtWidgets `
    --hidden-import psycopg2 `
    --hidden-import sounddevice `
    --hidden-import pyaudiowpatch `
    app\main.py
Write-Host "Built dist\AIInterviewCopilot\AIInterviewCopilot.exe"
