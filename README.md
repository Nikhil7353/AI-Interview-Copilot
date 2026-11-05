# AI Interview Copilot

A native Windows 10/11 desktop interview assistant built with **Python 3.10+** and **PySide6**. It combines hands-free system/microphone voice capture, local `faster-whisper` transcription, speaker separation, a **PostgreSQL + `pgvector`** personal knowledge base (resumes, verified candidate profile, and full project codebases), and real-time streaming AI responses via **Ollama** (local), **Groq**, or **OpenRouter**.

---

## Complete Feature Breakdown

### 1. 3-Workspace Glassmorphism UI + Frameless Live HUD
- **Workspace 1 — `1. Live Copilot`:**
  - Live question stage (`❓ QUESTION`) with borderless status indicator (`● Ready`, `● Auto-Listen ON`, `Answer generated in 0.8s`).
  - Audio & action bar: **`Auto-Listen`**, **`Generate answer · Ctrl+Enter`**, **`Record`**, **`Transcribe file`**, and **`Speakers`**.
  - Streaming spoken answer stage (`💡 ANSWER`) formatted as scannable, first-person spoken bullet points (`• ...`).
  - Bottom style & action bar: **`Copy`** (`Ctrl+Shift+C`), **`Short`**, **`Balanced`**, **`Detailed`**, **`STAR`**, and **`Regenerate`** (with automatic duplicate-question protection).
  - Right-hand **Matched Evidence & Session Questions Sidebar**: displays the exact verified profile facts and project files used for the current answer alongside clickable session history.
- **Workspace 2 — `2. Knowledge & Profile`:**
  - Full-width document & codebase manager (`Import file`, `Import folder`, `Analyze Project with AI`, `Re-index`, `Remove`, `Clear all`) with a live search filter and `0%–100%` import progress bar (`QProgressBar`).
  - **Grouped Project Folder Rows:** Uploaded project folders collapse into a single `📁 <Project Name> (N files)` (`PROJECT FOLDER`) row so entire codebases can be inspected, re-indexed, or removed in one click.
  - **End-to-End Architecture & Data Flow Viewer:** Selecting a project folder displays its detected tech stack, 5 end-to-end system flows (Auth/JWT, KYC/OCR, WebSockets, Celery tasks, GST billing), and codebase layer breakdown (Models, Views/Serializers, Services/Workers).
- **Workspace 3 — `3. Mock Practice`:**
  - Side-by-side practice workspace with 6 topic banks (`Python`, `Django`, `REST APIs`, `SQL`, `Behavioral`, `Resume`), unseen question rotation, candidate answer editor, streaming **Check my answer** AI coach feedback, and **Send to Live Copilot & Generate**.
- **Frameless Translucent Live HUD (`Live HUD · Ctrl+Shift+Space`):**
  - Always-on-top, draggable, see-through overlay (`Qt.FramelessWindowHint` + `WA_TranslucentBackground`) with an adjustable **Opacity slider (`45%–100%`)**, `Collapse` toggle, live audio status pill (`● Audio: Listening` / `🔥 Question detected` / `✓ Answer generated`), `❓ QUESTION` box, and `💡 ANSWER` bullet box.

### 2. Hands-Free Audio Pipeline & Speaker Separation
- **Simultaneous System Audio Loopback + Microphone (`app/audio/capture.py`):**
  - Captures Windows WASAPI speaker/headphone output via `PyAudioWPatch` (hears interviewers on Zoom, Google Meet, or Teams even when wearing headphones) and microphone input via `sounddevice`.
  - Configurable in Settings: `System + Mic`, `System audio only`, or `Microphone only`.
- **Automatic Voice Activity Detection (`ContinuousListener`):**
  - Detects speech onset with pre-roll buffering and automatically flushes the utterance after `0.85s` of silence.
- **Fast In-Memory Whisper Transcription & Greeting Filter (`app/audio/transcription.py`):**
  - Transcribes 16 kHz PCM arrays directly in memory using a cached `faster-whisper` (`small.en`, `int8`, `beam_size=1`) model without disk I/O delay.
  - Automatically strips `[0.0-5.0]` timestamps and `Speaker 1:` prefixes, ignores mic checks and small talk (*"can you hear me"*, *"good morning"*), and auto-triggers answer generation when a real question is spoken.
- **Speaker Separation (`app/audio/diarization.py`):**
  - Clusters audio segments using RMS energy, FFT spectral centroid, and zero-crossing rate into `Interviewer` and `Candidate` turns (customizable anytime via the **`Speakers`** button).

### 3. Deep Project Analyzer, Resume Auto-Fill & Hybrid `pgvector` Retrieval
- **Static Project Folder Analyzer (`app/knowledge/project_summary.py`):**
  - Scans up to 500 repository files while skipping `.venv`, `node_modules`, `.git`, `migrations`, `.env`, lockfiles, and secrets. Never executes repository code.
  - **`Analyze Project with AI`:** Uses your active LLM (**Groq**, **OpenRouter NVIDIA Nemotron**, or **Ollama**) grounded in your verified profile and codebase map to generate a 4-part **AI Project Architecture Dossier** (Elevator Pitch, Core Architecture & Data Flow, Key Engineering Challenges Solved, and Top 5 Deep-Dive Q&A).
- **1-Click Resume Auto-Fill & Verification Gate (`app/knowledge/profile.py`, `app/ui/profile_editor.py`):**
  - **`Auto-fill from resume`** parses PDF/DOCX resumes into structured sections (`Professional summary`, `Skills and technologies`, `Employment history`, `Projects`, `Education`, `Certifications`, `Technical challenges`, and `Achievements`) and marks confirmed facts **`Verified`**.
  - Supports custom **Answer length**, **Tone** (`Conversational`, `Professional`, `Direct`), and **Target job description** alignment.
  - **Strict Anti-Hallucination Gate:** Only `Verified` facts are injected into prompts; items marked `Needs review`, `Unknown`, or `Outdated` are held back and shown in the preview panel.
- **Native PostgreSQL + `pgvector` Hybrid Search (`app/knowledge/store.py`, `app/knowledge/retrieval.py`):**
  - Generates 384-dimension embeddings via local Ollama `all-minilm` and runs native PostgreSQL cosine similarity (`1 - (c.embedding <=> %s::vector)`) combined with stopword-filtered keyword overlap, filename matching, and per-file diversity caps.

### 4. Windows Desktop Integration & Packaging
- **Windows 11 DWM Dark Chrome & Glass Theme (`app/windows/dwm_backdrop.py`, `app/ui/theme.py`):**
  - Custom `GlassCanvas` aurora mesh backdrop, `GlassFrame` frosted cards with specular top rim lighting, and Win32 DWM dark title bar / Mica & Acrylic backdrop attributes.
- **Global Hotkeys & Capture Affinity (`app/windows/hotkeys.py`, `app/windows/capture_affinity.py`):**
  - Configurable Win32 `RegisterHotKey` shortcuts (`Ctrl+Shift+Space`, `Ctrl+Shift+C`, `Ctrl+Shift+P`) with app-local `QShortcut` fallback.
  - Best-effort Windows `SetWindowDisplayAffinity` (`WDA_EXCLUDEFROMCAPTURE`) option in Settings, verified via `GetWindowDisplayAffinity`.
- **1-Click In-App Restart & PyInstaller Build:**
  - Header **`Restart`** button cleanly relaunches both Python development sessions and frozen `.exe` builds.

---

## Project Structure

```text
AI Interview Copilot/
├── app/
│   ├── ai/
│   │   ├── prompt_builder.py     # First-person spoken bullet prompts, tone & JD alignment
│   │   └── providers.py          # Streaming clients for Ollama, Groq, and OpenRouter
│   ├── assets/
│   │   ├── app-icon.ico          # Windows application & taskbar icon
│   │   └── app-icon.png
│   ├── audio/
│   │   ├── capture.py            # WASAPI loopback (PyAudioWPatch) + Mic recorder & ContinuousListener VAD
│   │   ├── diarization.py        # 2-speaker audio feature clustering (Interviewer / Candidate)
│   │   └── transcription.py      # Cached faster-whisper STT, metadata stripper & greeting filter
│   ├── interview/
│   │   ├── dedup.py              # Session duplicate-question normalization & detection
│   │   ├── evaluation.py         # Practice mode AI coach evaluation prompt builder
│   │   └── questions.py          # Curated question banks (Python, Django, REST, SQL, Behavioral, Resume)
│   ├── knowledge/
│   │   ├── embeddings.py         # Local Ollama all-minilm (384-d) vector client
│   │   ├── ingestion.py          # PDF (PyMuPDF), DOCX, JSON, Markdown & code-boundary chunker
│   │   ├── profile.py            # CandidateProfile model & generic section-based resume parser
│   │   ├── project_summary.py    # Static codebase analyzer, flow map builder & AI dossier prompt
│   │   ├── retrieval.py          # Hybrid pgvector + keyword + verified profile retrieval engine
│   │   └── store.py              # PostgreSQL + pgvector store (with SQLite unit-test backend)
│   ├── ui/
│   │   ├── floating_panel.py     # Frameless translucent Live HUD overlay
│   │   ├── knowledge_panel.py    # Workspace 2: grouped project folders, progress bar & flow viewer
│   │   ├── main_window.py        # 3-Workspace main window, audio threads & shortcuts
│   │   ├── practice_panel.py     # Workspace 3: mock interview practice & streaming coach feedback
│   │   ├── profile_editor.py     # Candidate profile editor dialog with verification gate
│   │   ├── settings_dialog.py    # Scrollable glass settings dialog
│   │   ├── theme.py              # GlassCanvas, GlassFrame & QSS stylesheet
│   │   └── workers.py            # Background AnswerWorker (QThread retrieval + token streaming)
│   ├── windows/
│   │   ├── capture_affinity.py   # Win32 SetWindowDisplayAffinity / GetWindowDisplayAffinity
│   │   ├── dwm_backdrop.py       # Windows 10/11 DWM immersive dark mode & Mica/Acrylic backdrop
│   │   └── hotkeys.py            # Win32 RegisterHotKey / UnregisterHotKey manager
│   ├── config.py                 # AppConfig persistence (%APPDATA%\AIInterviewCopilot\settings.json)
│   └── main.py                   # Entry point & Windows AppUserModelID setup
├── docs/
│   └── screen_share_test.html
├── scripts/
│   ├── build_windows.ps1         # PyInstaller standalone Windows .exe builder
│   ├── check_db.py               # PostgreSQL + pgvector connectivity diagnostic
│   └── install_pgvector.ps1      # Administrator script to install pgvector on PostgreSQL 18
├── tests/
│   ├── test_core.py
│   ├── test_interview.py
│   └── test_knowledge.py
├── .env.example
├── pytest.ini
├── requirements.txt
└── README.md
```

---

## Requirements

- **OS:** Windows 10 (build 19041+) or Windows 11
- **Python:** 3.10 or newer
- **Database:** PostgreSQL 16+ with the `pgvector` extension
- **AI Provider:** Local [Ollama](https://ollama.com) (`llama3.2:3b` and `all-minilm`), or optional `GROQ_API_KEY` / `OPENROUTER_API_KEY` environment variables

---

## Quick Start (PowerShell)

```powershell
cd "D:\AI Interview Copilot"
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

---

## AI Provider Setup

### 1. Local Ollama (Default)

Pull the answer model and the 384-d embedding model once:

```powershell
ollama pull llama3.2:3b
ollama pull all-minilm
```

### 2. Groq (Optional Fast Cloud Streaming)

Set your API key in your Windows user environment (or in a local `.env` file, which is git-ignored):

```powershell
[Environment]::SetEnvironmentVariable("GROQ_API_KEY", "your-groq-key", "User")
```

In **Settings**, select **Groq · cloud** and model `llama-3.3-70b-versatile`.

### 3. OpenRouter (Optional Cloud Streaming)

```powershell
[Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", "your-openrouter-key", "User")
```

In **Settings**, select **OpenRouter · cloud** and set your model (e.g. `nvidia/nemotron-3.5-super-vl:free`).

---

## PostgreSQL + `pgvector` Setup

The app connects to PostgreSQL by default (`postgresql://postgres:123@localhost:5432/interview_copilot`) and automatically creates the `interview_copilot` database, tables, and `vector` extension on launch.

If `pgvector` is not yet installed on your local PostgreSQL instance, run the helper script once in an elevated PowerShell window:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_pgvector.ps1
```

Verify database connectivity at any time with:

```powershell
.\.venv\Scripts\python.exe scripts\check_db.py
```

---

## Keyboard Shortcuts

| Action | Default Shortcut |
| :--- | :--- |
| Toggle Live HUD Overlay | `Ctrl+Shift+Space` |
| Generate Answer | `Ctrl+Enter` |
| Copy Suggested Answer | `Ctrl+Shift+C` |
| Pause / Resume Assistant | `Ctrl+Shift+P` |

---

## Building the Windows Executable (`.exe`)

Package the application into a standalone Windows folder (`dist\AIInterviewCopilot\AIInterviewCopilot.exe`) using PyInstaller:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

---

## Running Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
