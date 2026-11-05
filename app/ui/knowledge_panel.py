"""Knowledge Base panel: document import, profile management, and context preview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ai.providers import ProviderError, iter_provider_response
from app.config import load_config
from app.knowledge.ingestion import extract_document, scan_directory, is_forbidden
from app.knowledge.profile import CandidateProfile, extract_profile_from_resume_text, save_candidate_profile
from app.knowledge.project_summary import (
    analyze_project_folder,
    build_project_analysis_prompt,
    build_project_flow_overview,
    summarize_indexed_files,
    summarize_store_for_ai_analysis,
)
from app.knowledge.retrieval import retrieve, build_context_string
from app.knowledge.store import KnowledgeStore
from app.ui.theme import GlassFrame, KNOWLEDGE_PANEL_STYLES


class ProjectAnalysisWorker(QThread):
    """Background worker that asks Groq / OpenRouter / Ollama to analyze the indexed project."""

    partial = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        store: KnowledgeStore,
        project_title: str = "Stock Market Advisory Platform",
        doc_ids: list[int] | None = None,
        project_root: str | None = None,
    ):
        super().__init__()
        self.store = store
        self.project_title = project_title
        self.doc_ids = doc_ids
        self.project_root = project_root

    def run(self):
        try:
            digest = summarize_store_for_ai_analysis(
                self.store,
                project_title=self.project_title,
                doc_ids=self.doc_ids,
            )
            if not digest.strip():
                self.failed.emit("Import a project folder or files first before running AI Project Analysis.")
                return
            prompt = build_project_analysis_prompt(digest, project_title=self.project_title)
            cfg = load_config()
            parts: list[str] = []
            for piece in iter_provider_response(
                prompt,
                cfg.provider,
                cfg.model,
                ollama_url=cfg.ollama_url,
                openrouter_url=cfg.openrouter_url,
                groq_url=cfg.groq_url,
                max_tokens=700,
            ):
                parts.append(piece)
                self.partial.emit("".join(parts))
            dossier = "".join(parts).strip()
            if not dossier:
                raise ProviderError("The AI provider returned an empty project analysis.")
            brief_path = f"ai_architecture_dossier::{self.project_title}::project_brief"
            doc_id = self.store.add_document(
                filename=f"AI Project Architecture Dossier — {self.project_title}",
                path=brief_path,
                file_type="project_brief",
                size_bytes=len(dossier),
                metadata={
                    "kind": "ai_architecture_dossier",
                    "project_name": self.project_title,
                    "project_root": self.project_root or "",
                },
                status="indexed",
            )
            self.store.add_chunks(doc_id, [(dossier, f"AI architecture dossier for {self.project_title}")])
            self.finished.emit(dossier)
        except Exception as exc:
            self.failed.emit(str(exc))


class ImportWorker(QThread):
    """Background worker for importing a directory of documents with live % progress."""
    progress = Signal(int, int, str)  # (current, total, filename)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, store: KnowledgeStore, directory: str = "", files: list[Path] | None = None):
        super().__init__()
        self.store = store
        self.directory = directory
        self.files = files

    def run(self):
        try:
            results = []
            files = self.files if self.files is not None else scan_directory(self.directory)
            total = len(files)
            root_meta = {}
            if self.directory:
                folder_p = Path(self.directory).resolve()
                root_meta = {"project_root": str(folder_p), "project_name": folder_p.name}
            for idx, path in enumerate(files, 1):
                self.progress.emit(idx, total, path.name)
                extracted = extract_document(path)
                merged_meta = {**(extracted.metadata or {}), **root_meta}
                if extracted.error:
                    self.store.add_document(
                        filename=extracted.filename,
                        path=str(path),
                        file_type=extracted.file_type,
                        size_bytes=extracted.size_bytes,
                        metadata=merged_meta,
                        status="error",
                        error_message=extracted.error,
                    )
                    results.append((path, extracted.error, False))
                    continue

                doc_id = self.store.add_document(
                    filename=extracted.filename,
                    path=str(path),
                    file_type=extracted.file_type,
                    size_bytes=extracted.size_bytes,
                    metadata=merged_meta,
                    status="indexed",
                )
                if extracted.chunks:
                    ref = path.name
                    if self.directory:
                        try:
                            ref = str(path.relative_to(self.directory))
                        except ValueError:
                            pass
                    # Fast insert during bulk folder import; embeddings backfill in background
                    self.store.add_chunks(
                        doc_id,
                        [(text, ref) for text, _old in extracted.chunks],
                        embed_now=(total <= 2),
                    )
                results.append((path, extracted.error or "Indexed", True))
            if self.directory:
                self._save_project_brief()
            self.finished.emit(results)
        except Exception as exc:  # keep UI responsive on failure
            self.failed.emit(str(exc))

    def _save_project_brief(self):
        brief = analyze_project_folder(self.directory)
        if not brief.strip():
            return
        folder = Path(self.directory).resolve()
        brief_path = str(folder) + "::project-brief"
        doc_id = self.store.add_document(
            filename=f"{folder.name} project brief",
            path=brief_path,
            file_type="project_brief",
            size_bytes=len(brief),
            metadata={"kind": "project_brief", "project_root": str(folder), "project_name": folder.name},
            status="indexed",
        )
        for document in self.store.list_documents():
            if document.path == brief_path and document.id is not None:
                doc_id = document.id
                break
        self.store.add_chunks(doc_id, [(brief, "project brief")], embed_now=False)


class KnowledgePanel(QWidget):
    """Knowledge Base section embedded in the main dashboard.

    Emits `context_ready(str)` with a context string built from retrieved
    documents and profile facts whenever the current question changes.
    """
    context_ready = Signal(str)
    edit_profile = Signal()

    def __init__(self, store: KnowledgeStore | None = None, parent=None):
        super().__init__(parent)
        self.store = store or KnowledgeStore()
        self.current_question = ""
        self._import_thread = None
        self._import_worker = None
        self._analysis_worker = None
        self._build_ui()
        self._refresh_documents()
        self._refresh_profile_summary()

    # ---------------- UI construction ----------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ---- Left Column (58%): Indexed Documents & Codebase (Sleek GlassFrame) ----
        docs_group = GlassFrame()
        docs_layout = QVBoxLayout(docs_group)
        docs_layout.setContentsMargins(18, 16, 18, 16)
        docs_layout.setSpacing(10)

        docs_header_row = QHBoxLayout()
        docs_title = QLabel("📂 INDEXED DOCUMENTS & CODEBASE")
        docs_title.setObjectName("sectionLabel")
        docs_header_row.addWidget(docs_title)
        docs_header_row.addStretch()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter 68+ files by name or type…")
        self.search_input.setMaximumWidth(230)
        self.search_input.textChanged.connect(self._filter_documents_table)
        docs_header_row.addWidget(self.search_input)
        docs_layout.addLayout(docs_header_row)

        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        self.btn_import_file = QPushButton("Import file")
        self.btn_import_file.setObjectName("kbActionBtn")
        self.btn_import_file.clicked.connect(self.import_file)
        self.btn_import_dir = QPushButton("Import folder")
        self.btn_import_dir.setObjectName("kbActionBtn")
        self.btn_import_dir.clicked.connect(self.import_folder)
        self.btn_analyze_ai = QPushButton("Analyze Project with AI")
        self.btn_analyze_ai.setObjectName("primary")
        self.btn_analyze_ai.setToolTip("Use Groq / OpenRouter Nemotron / Ollama to generate a deep architecture & Q&A dossier from your indexed project")
        self.btn_analyze_ai.clicked.connect(self.analyze_project_with_ai)
        self.btn_reindex = QPushButton("Re-index")
        self.btn_reindex.setObjectName("kbActionBtn")
        self.btn_reindex.clicked.connect(self.reindex_selected)
        self.btn_reindex.setEnabled(False)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setObjectName("kbActionBtn")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_remove.setEnabled(False)
        self.btn_clear_all = QPushButton("Clear all")
        self.btn_clear_all.setObjectName("kbActionBtn")
        self.btn_clear_all.setToolTip("Remove all indexed documents and project folders at once")
        self.btn_clear_all.clicked.connect(self.clear_all_documents)
        import_row.addWidget(self.btn_import_file)
        import_row.addWidget(self.btn_import_dir)
        import_row.addWidget(self.btn_analyze_ai)
        import_row.addStretch()
        import_row.addWidget(self.btn_reindex)
        import_row.addWidget(self.btn_remove)
        import_row.addWidget(self.btn_clear_all)
        docs_layout.addLayout(import_row)

        self.project_summary = QLabel("No indexed project files yet.")
        self.project_summary.setObjectName("kbMuted")
        self.project_summary.setWordWrap(True)
        docs_layout.addWidget(self.project_summary)

        self.doc_table = QTableWidget(0, 4)
        self.doc_table.setMinimumHeight(320)
        self.doc_table.setHorizontalHeaderLabels(["File", "Type", "Size", "Status"])
        self.doc_table.verticalHeader().setVisible(False)
        self.doc_table.verticalHeader().setDefaultSectionSize(34)
        self.doc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.doc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.doc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.doc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.doc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.doc_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.doc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.doc_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.doc_table.itemSelectionChanged.connect(self._on_doc_selection_changed)
        self.doc_table.setAlternatingRowColors(True)
        docs_layout.addWidget(self.doc_table, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.hide()
        docs_layout.addWidget(self.progress_bar)

        self.import_status = QLabel("")
        self.import_status.setObjectName("kbMuted")
        self.import_status.setWordWrap(True)
        self.import_status.hide()
        docs_layout.addWidget(self.import_status)

        splitter.addWidget(docs_group)

        # ---- Right Column (42%): Candidate Profile + AI Project Dossier / Retrieved Context ----
        right_col = QWidget()
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        profile_group = GlassFrame()
        profile_layout = QVBoxLayout(profile_group)
        profile_layout.setContentsMargins(18, 16, 18, 14)
        profile_layout.setSpacing(8)

        prof_title = QLabel("👤 CANDIDATE PROFILE (VERIFIED FACTS GATE)")
        prof_title.setObjectName("sectionLabel")
        profile_layout.addWidget(prof_title)

        prof_row = QHBoxLayout()
        prof_row.setSpacing(8)
        self.btn_edit_profile = QPushButton("Edit profile…")
        self.btn_edit_profile.setObjectName("kbActionBtn")
        self.btn_edit_profile.clicked.connect(self.edit_profile_requested)
        self.btn_autofill_profile = QPushButton("Auto-fill from resume")
        self.btn_autofill_profile.setObjectName("kbActionBtn")
        self.btn_autofill_profile.setToolTip("Extract your summary, skills, roles, and projects from your indexed resume and mark them Verified")
        self.btn_autofill_profile.clicked.connect(self.autofill_profile_from_resume)
        self.btn_clear_profile = QPushButton("Clear")
        self.btn_clear_profile.setObjectName("kbActionBtn")
        self.btn_clear_profile.clicked.connect(self.clear_profile)
        prof_row.addWidget(self.btn_edit_profile)
        prof_row.addWidget(self.btn_autofill_profile)
        prof_row.addStretch()
        prof_row.addWidget(self.btn_clear_profile)
        profile_layout.addLayout(prof_row)

        self.profile_summary = QLabel("No profile data yet.")
        self.profile_summary.setObjectName("kbMuted")
        self.profile_summary.setWordWrap(True)
        profile_layout.addWidget(self.profile_summary)
        right_layout.addWidget(profile_group)

        ctx_group = GlassFrame()
        ctx_layout = QVBoxLayout(ctx_group)
        ctx_layout.setContentsMargins(18, 16, 18, 16)
        ctx_layout.setSpacing(8)

        ctx_title = QLabel("🧠 PROJECT ARCHITECTURE DOSSIER & RETRIEVED CONTEXT")
        ctx_title.setObjectName("sectionLabel")
        ctx_layout.addWidget(ctx_title)

        self.ctx_question = QLabel("Click 'Analyze Project with AI' or ask a question to inspect matched evidence.")
        self.ctx_question.setObjectName("kbMuted")
        self.ctx_question.setWordWrap(True)
        ctx_layout.addWidget(self.ctx_question)

        self.ctx_preview = QTextEdit()
        self.ctx_preview.setReadOnly(True)
        self.ctx_preview.setMinimumHeight(180)
        self.ctx_preview.setPlaceholderText(
            "• Click 'Analyze Project with AI' to generate a complete architectural breakdown and top interview Q&A for your project.\n"
            "• Or submit an interview question to inspect the exact verified facts and code excerpts sent to the model."
        )
        ctx_layout.addWidget(self.ctx_preview, 1)

        self.ctx_evidence = QLabel("Ready · Verified profile facts + pgvector semantic search active")
        self.ctx_evidence.setObjectName("kbMuted")
        self.ctx_evidence.setWordWrap(True)
        ctx_layout.addWidget(self.ctx_evidence)
        right_layout.addWidget(ctx_group, 1)

        splitter.addWidget(right_col)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([640, 460])
        layout.addWidget(splitter, 1)

        self.setStyleSheet(KNOWLEDGE_PANEL_STYLES)

    # ---------------- Document operations ----------------

    @staticmethod
    def _infer_project_group(doc) -> tuple[str, str] | None:
        """Return (project_root_key, display_name) if this document belongs to a multi-file project folder."""
        meta = doc.metadata if isinstance(doc.metadata, dict) else {}
        if meta.get("project_root"):
            root = str(meta["project_root"])
            name = str(meta.get("project_name") or Path(root).name)
            return root, name
        raw_path = str(doc.path or "").split("::project-brief")[0]
        if not raw_path or raw_path.startswith("ai_architecture_dossier") or raw_path.startswith("/tmp/"):
            return None
        try:
            p = Path(raw_path)
        except Exception:
            return None
        lower_parts = [part.lower() for part in p.parts]
        if "downloads" in lower_parts or "desktop" in lower_parts or "temp" in lower_parts or "pytest" in raw_path.lower():
            return None
        if len(p.parts) >= 3:
            parent = p.parent
            return str(parent), parent.name
        return None

    def _refresh_documents(self):
        self.doc_table.setRowCount(0)
        all_docs = self.store.list_documents()
        names = [doc.filename for doc in all_docs]

        # Group project-folder files when 2+ files share the same project folder
        folder_buckets: dict[str, list] = {}
        folder_names: dict[str, str] = {}
        standalone_docs: list = []

        for doc in all_docs:
            grp = self._infer_project_group(doc)
            if grp is not None:
                root_key, disp_name = grp
                folder_buckets.setdefault(root_key, []).append(doc)
                folder_names[root_key] = disp_name
            else:
                standalone_docs.append(doc)

        # Merge subfolders (e.g. ".../project/backend") into their parent project folder (".../project")
        sorted_roots = sorted(folder_buckets.keys(), key=lambda k: len(k))
        merged_buckets: dict[str, list] = {}
        merged_names: dict[str, str] = {}
        for root_key in sorted_roots:
            docs_in_bucket = folder_buckets[root_key]
            norm_root = root_key.rstrip("\\/").lower()
            parent_match = None
            for existing_root in merged_buckets:
                norm_existing = existing_root.rstrip("\\/").lower()
                if norm_root == norm_existing or norm_root.startswith(norm_existing + "\\") or norm_root.startswith(norm_existing + "/"):
                    parent_match = existing_root
                    break
            if parent_match is not None:
                merged_buckets[parent_match].extend(docs_in_bucket)
            else:
                # Also collapse ".../project/backend" up to ".../project" if parent isn't a top drive/user folder
                p_obj = Path(root_key)
                if p_obj.name.lower() in {"backend", "frontend", "src", "app", "server", "client"} and len(p_obj.parts) >= 3:
                    parent_dir = str(p_obj.parent)
                    merged_buckets.setdefault(parent_dir, []).extend(docs_in_bucket)
                    merged_names[parent_dir] = p_obj.parent.name
                else:
                    merged_buckets[root_key] = list(docs_in_bucket)
                    merged_names[root_key] = folder_names.get(root_key, p_obj.name)

        display_rows: list[dict] = []
        for root_key, group_docs in merged_buckets.items():
            if len(group_docs) >= 2:
                total_size = sum(d.size_bytes for d in group_docs)
                code_files = [d for d in group_docs if d.file_type != "project_brief"]
                count = len(code_files) or len(group_docs)
                disp = merged_names.get(root_key, Path(root_key).name)
                display_rows.append(
                    {
                        "label": f"📁 {disp} ({count} files)",
                        "type": "PROJECT FOLDER",
                        "size": total_size,
                        "status": "indexed" if any(d.status == "indexed" for d in group_docs) else group_docs[0].status,
                        "doc_ids": [d.id for d in group_docs if d.id is not None],
                        "project_root": root_key,
                        "title": disp,
                    }
                )
            else:
                standalone_docs.extend(group_docs)

        for doc in standalone_docs:
            if doc.id is None:
                continue
            display_rows.append(
                {
                    "label": doc.filename,
                    "type": doc.file_type.upper(),
                    "size": doc.size_bytes,
                    "status": doc.status,
                    "doc_ids": [doc.id],
                    "project_root": None,
                    "title": doc.filename,
                }
            )

        for item in display_rows:
            row = self.doc_table.rowCount()
            self.doc_table.insertRow(row)

            name_item = QTableWidgetItem(item["label"])
            first_id = item["doc_ids"][0] if item["doc_ids"] else None
            name_item.setData(Qt.ItemDataRole.UserRole, first_id)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, item["doc_ids"])
            name_item.setData(Qt.ItemDataRole.UserRole + 2, item["project_root"])
            name_item.setData(Qt.ItemDataRole.UserRole + 3, item["title"])
            self.doc_table.setItem(row, 0, name_item)

            self.doc_table.setItem(row, 1, QTableWidgetItem(item["type"]))
            self.doc_table.setItem(row, 2, QTableWidgetItem(self._format_size(item["size"])))

            status_item = QTableWidgetItem(str(item["status"]).upper())
            if item["status"] == "indexed":
                status_item.setForeground(QColor("#34d399"))
            elif item["status"] == "error":
                status_item.setForeground(QColor("#f87171"))
            else:
                status_item.setForeground(QColor("#fbbf24"))
            self.doc_table.setItem(row, 3, status_item)

        if hasattr(self, "btn_clear_all"):
            self.btn_clear_all.setEnabled(bool(all_docs))
        self.project_summary.setText(summarize_indexed_files(names))

    def _filter_documents_table(self, query: str):
        needle = query.strip().lower()
        for row in range(self.doc_table.rowCount()):
            name_item = self.doc_table.item(row, 0)
            type_item = self.doc_table.item(row, 1)
            text = f"{name_item.text() if name_item else ''} {type_item.text() if type_item else ''}".lower()
            self.doc_table.setRowHidden(row, bool(needle and needle not in text))

    def analyze_project_with_ai(self):
        if self._analysis_worker is not None and self._analysis_worker.isRunning():
            return

        # Check if a specific project folder is selected in the doc_table
        row = self.doc_table.currentRow()
        project_title = "Stock Market Advisory Platform"
        doc_ids = None
        project_root = None

        if row >= 0:
            name_item = self.doc_table.item(row, 0)
            if name_item:
                item_doc_ids = name_item.data(Qt.ItemDataRole.UserRole + 1)
                item_root = name_item.data(Qt.ItemDataRole.UserRole + 2)
                item_title = name_item.data(Qt.ItemDataRole.UserRole + 3)
                if item_doc_ids and len(item_doc_ids) > 1:
                    doc_ids = item_doc_ids
                    project_root = item_root
                    project_title = str(item_title) if item_title else project_title

        # If nothing specific selected, default to the first indexed project folder
        if doc_ids is None:
            for r in range(self.doc_table.rowCount()):
                type_item = self.doc_table.item(r, 1)
                if type_item and "PROJECT" in type_item.text().upper():
                    n_item = self.doc_table.item(r, 0)
                    if n_item:
                        doc_ids = n_item.data(Qt.ItemDataRole.UserRole + 1)
                        project_root = n_item.data(Qt.ItemDataRole.UserRole + 2)
                        item_title = n_item.data(Qt.ItemDataRole.UserRole + 3)
                        project_title = str(item_title) if item_title else project_title
                        break

        self.btn_analyze_ai.setEnabled(False)
        self.ctx_question.setText(f"Analyzing {project_title} architecture with AI…")
        self.ctx_preview.clear()
        self.ctx_evidence.setText(f"Building Project Architecture Dossier for {project_title}…")
        self._analysis_worker = ProjectAnalysisWorker(
            self.store,
            project_title=project_title,
            doc_ids=doc_ids,
            project_root=project_root,
        )
        self._analysis_worker.partial.connect(self.ctx_preview.setPlainText)
        self._analysis_worker.finished.connect(self._on_project_analysis_done)
        self._analysis_worker.failed.connect(self._on_project_analysis_failed)
        self._analysis_worker.finished.connect(self._analysis_worker.deleteLater)
        self._analysis_worker.failed.connect(self._analysis_worker.deleteLater)
        self._analysis_worker.start()

    def _on_project_analysis_done(self, dossier: str):
        from app.knowledge import project_summary

        project_summary._FLOW_MAP_CACHE.clear()
        self.btn_analyze_ai.setEnabled(True)
        self.ctx_question.setText("AI Project Architecture Dossier (Saved & Indexed for Live Q&A)")
        self.ctx_preview.setPlainText(dossier)
        self.ctx_evidence.setText("Saved to Knowledge Base · Live Copilot will use this architecture map on project questions")
        self._refresh_documents()

    def _on_project_analysis_failed(self, message: str):
        self.btn_analyze_ai.setEnabled(True)
        self.ctx_question.setText("Project analysis failed")
        self.ctx_evidence.setText(message)

    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def _on_doc_selection_changed(self):
        has = bool(self.doc_table.selectedItems())
        self.btn_remove.setEnabled(has)
        self.btn_reindex.setEnabled(has)
        row = self.doc_table.currentRow()
        if row < 0:
            return
        name_item = self.doc_table.item(row, 0)
        if name_item is None:
            return
        doc_ids = name_item.data(Qt.ItemDataRole.UserRole + 1) or []
        title = name_item.data(Qt.ItemDataRole.UserRole + 3) or name_item.text()
        if not doc_ids:
            return
        # Show structured Architecture & Flow Map for project folders, or clean summary for single documents
        if not self.current_question:
            if len(doc_ids) > 1:
                flow_map = build_project_flow_overview(self.store, doc_ids, str(title))
                self.ctx_question.setText(f"Architecture & End-to-End Flow Map — {title} ({len(doc_ids)} files)")
                self.ctx_preview.setPlainText(flow_map)
                self.ctx_evidence.setText(
                    f"Showing full architecture & data flow across {len(doc_ids)} indexed files · Used automatically on project questions"
                )
                return

            preview_parts: list[str] = []
            for did in doc_ids[:4]:
                doc = self.store.get_document(did)
                if not doc:
                    continue
                chunks = self.store.get_chunks_for_document(did)
                if chunks:
                    preview_parts.append("\n\n".join(c.text for c in chunks[:3])[:2200])
            if preview_parts:
                self.ctx_question.setText(f"Document Overview — {title}")
                self.ctx_preview.setPlainText("\n\n".join(preview_parts))
                self.ctx_evidence.setText("Indexed in PostgreSQL + pgvector · Ready for live interview retrieval")

    def _selected_doc_id(self) -> int | None:
        items = self.doc_table.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select document to import",
            "",
            "Supported documents (*.pdf *.docx *.doc *.txt *.md *.markdown *.json *.py *.js *.ts *.tsx *.jsx);;All files (*)",
        )
        if not path:
            return
        self._start_file_import(path)

    def import_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Select folder to import")
        if not directory:
            return
        self._start_directory_import(directory)

    def _set_import_status(self, message: str):
        self.import_status.setText(message)
        self.import_status.setVisible(bool(message.strip()))

    def _on_import_progress(self, current: int, total: int, filename: str):
        pct = int(round((current / max(1, total)) * 100))
        self.progress_bar.show()
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{pct}%  ({current}/{total})")
        self._set_import_status(f"Indexing {pct}% ({current} of {total} files) — {filename}")

    def _start_file_import(self, path: str):
        self.btn_import_file.setEnabled(False)
        self.btn_import_dir.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self._set_import_status("Indexing file (0%)…")
        self._import_worker = ImportWorker(self.store, files=[Path(path)])
        self._import_thread = QThread(self)
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.failed.connect(self._on_import_failed)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_worker.failed.connect(self._import_thread.quit)
        self._import_thread.finished.connect(self._import_worker.deleteLater)
        self._import_thread.finished.connect(self._import_thread.deleteLater)
        self._import_thread.finished.connect(lambda: setattr(self, "_import_thread", None))
        self._import_thread.start()

    def _import_single(self, path: str):
        self._set_import_status("Extracting…")
        extracted = extract_document(path)
        if extracted.error:
            self.store.add_document(
                filename=extracted.filename,
                path=path,
                file_type=extracted.file_type,
                size_bytes=extracted.size_bytes,
                metadata=extracted.metadata,
                status="error",
                error_message=extracted.error,
            )
            self._set_import_status(f"Failed: {extracted.error}")
            self._refresh_documents()
            return

        doc_id = self.store.add_document(
            filename=extracted.filename,
            path=path,
            file_type=extracted.file_type,
            size_bytes=extracted.size_bytes,
            metadata=extracted.metadata,
            status="indexed",
        )
        if extracted.chunks:
            self.store.add_chunks(doc_id, extracted.chunks)
        self._set_import_status(f"Indexed {extracted.filename} ({len(extracted.chunks)} sections)")
        self._refresh_documents()

    def _start_directory_import(self, directory: str):
        self.btn_import_file.setEnabled(False)
        self.btn_import_dir.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self._set_import_status("Scanning project folder (0%)…")
        self._import_worker = ImportWorker(self.store, directory)
        self._import_thread = QThread(self)
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.failed.connect(self._on_import_failed)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_worker.failed.connect(self._import_thread.quit)
        self._import_thread.finished.connect(self._import_worker.deleteLater)
        self._import_thread.finished.connect(self._import_thread.deleteLater)
        self._import_thread.finished.connect(lambda: setattr(self, "_import_thread", None))
        self._import_thread.start()

    def _on_import_finished(self, results: list):
        indexed = sum(1 for _, _, ok in results if ok)
        failed = sum(1 for _, _, ok in results if not ok)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(f"100%  ({indexed} indexed)")
        self._set_import_status(
            f"100% Complete — Imported {indexed} file(s){f', {failed} failed' if failed else ''}. "
            "Project brief saved for real-time answers."
        )
        self.btn_import_file.setEnabled(True)
        self.btn_import_dir.setEnabled(True)
        self._refresh_documents()

    def _on_import_failed(self, message: str):
        self.progress_bar.hide()
        self._set_import_status(f"Import failed: {message}")
        self.btn_import_file.setEnabled(True)
        self.btn_import_dir.setEnabled(True)

    def remove_selected(self):
        row = self.doc_table.currentRow()
        if row < 0:
            return
        name_item = self.doc_table.item(row, 0)
        if name_item is None:
            return
        doc_ids = name_item.data(Qt.ItemDataRole.UserRole + 1) or []
        if not doc_ids:
            single = name_item.data(Qt.ItemDataRole.UserRole)
            if single is not None:
                doc_ids = [single]
        if not doc_ids:
            return
        title = name_item.data(Qt.ItemDataRole.UserRole + 3) or name_item.text()
        prompt_text = (
            f"Remove project folder '{title}' and all {len(doc_ids)} indexed files from the knowledge base?"
            if len(doc_ids) > 1
            else f"Remove '{title}' from the knowledge base? Its extracted text and chunks will be deleted."
        )
        reply = QMessageBox.question(
            self,
            "Remove document",
            prompt_text,
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for did in doc_ids:
            self.store.remove_document(did)
        self._set_import_status(f"Removed '{title}'")
        self._refresh_documents()

    def clear_all_documents(self):
        docs = self.store.list_documents()
        if not docs:
            return
        reply = QMessageBox.question(
            self,
            "Clear all documents",
            f"Remove all {len(docs)} indexed files and project folders from the knowledge base?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if hasattr(self.store, "clear_documents"):
            self.store.clear_documents()
        else:
            for doc in docs:
                if doc.id is not None:
                    self.store.remove_document(doc.id)
        self._set_import_status("Cleared all indexed documents and project folders.")
        self._refresh_documents()

    def reindex_selected(self):
        row = self.doc_table.currentRow()
        if row >= 0:
            name_item = self.doc_table.item(row, 0)
            project_root = name_item.data(Qt.ItemDataRole.UserRole + 2) if name_item else None
            if project_root and Path(project_root).is_dir():
                self._start_directory_import(str(project_root))
                return
        doc_id = self._selected_doc_id()
        if doc_id is None:
            return
        doc = self.store.get_document(doc_id)
        if not doc:
            return
        self._set_import_status(f"Re-indexing {doc.filename}…")
        extracted = extract_document(doc.path)
        if extracted.error:
            self.store.add_document(
                filename=extracted.filename,
                path=doc.path,
                file_type=extracted.file_type,
                size_bytes=extracted.size_bytes,
                metadata=extracted.metadata,
                status="error",
                error_message=extracted.error,
            )
            self._set_import_status(f"Re-index failed: {extracted.error}")
        else:
            new_id = self.store.add_document(
                filename=extracted.filename,
                path=doc.path,
                file_type=extracted.file_type,
                size_bytes=extracted.size_bytes,
                metadata=extracted.metadata,
                status="indexed",
            )
            if extracted.chunks:
                self.store.add_chunks(new_id, extracted.chunks)
            self._set_import_status(f"Re-indexed {extracted.filename} ({len(extracted.chunks)} sections)")
        self._refresh_documents()

    # ---------------- Profile ----------------

    def _refresh_profile_summary(self):
        profile = self.store.get_full_profile()
        if not profile:
            self.profile_summary.setText("No profile data yet. Import a resume or edit the profile manually.")
            return
        skills = profile.get("skills", [])
        jobs = profile.get("employment", [])
        projects = profile.get("projects", [])
        summary = profile.get("professional_summary", "")
        bits = []
        if summary:
            bits.append(f'Summary: "{summary[:80]}…"' if len(summary) > 80 else f'Summary: "{summary}"')
        if skills:
            bits.append(f"{len(skills)} skill(s)")
        if jobs:
            bits.append(f"{len(jobs)} role(s)")
        if projects:
            bits.append(f"{len(projects)} project(s)")
        status = profile.get("overall_status", "needs_review")
        self.profile_summary.setText(" · ".join(bits) if bits else "Profile partially filled")
        self.profile_summary.setToolTip(f"Overall status: {status}")

    def edit_profile_requested(self):
        self.edit_profile.emit()

    def autofill_profile_from_resume(self) -> bool:
        docs = self.store.list_documents()
        resume_doc = None
        for doc in docs:
            if doc.status == "indexed" and "resume" in doc.filename.lower():
                resume_doc = doc
                break
        if resume_doc is None:
            for doc in docs:
                if doc.status == "indexed" and doc.file_type in {"docx", "pdf"}:
                    resume_doc = doc
                    break
        if resume_doc is None or resume_doc.id is None:
            self._set_import_status("Import a resume PDF or DOCX first to auto-fill your profile.")
            return False
        chunks = self.store.get_chunks_for_document(resume_doc.id)
        full_text = "\n\n".join(c.text for c in chunks if c.text)
        if not full_text.strip():
            return False
        profile = extract_profile_from_resume_text(full_text, status="verified")
        save_candidate_profile(self.store, profile)
        self._refresh_profile_summary()
        self._set_import_status(
            f"Auto-filled and Verified profile from {resume_doc.filename} "
            f"({len(profile.skills)} skills, {len(profile.employment)} roles, {len(profile.projects)} projects)."
        )
        if self.current_question:
            self._update_context_preview()
        return True

    def clear_profile(self):
        reply = QMessageBox.question(
            self, "Clear profile",
            "Delete all candidate profile data? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.store.clear_profile()
        self._refresh_profile_summary()
        self.ctx_preview.clear()
        self.ctx_evidence.setText("Profile cleared · no personal evidence will be used")

    # ---------------- Context retrieval ----------------

    def set_current_question(self, question: str, precomputed: tuple[str, object] | None = None) -> str:
        self.current_question = question.strip()
        self.ctx_question.setText(question if question else "No question submitted yet.")
        if precomputed is not None:
            context, result = precomputed
            self._render_retrieval(context, result)
            return context
        return self._update_context_preview()

    def _render_retrieval(self, context: str, result) -> None:
        held = ""
        if result and getattr(result, "needs_review_items", None):
            held = "\n\nHeld back (not verified — not sent to the model):\n" + "\n".join(
                f"- [{item.source_ref}] {item.text}" for item in result.needs_review_items
            )
        self.ctx_preview.setPlainText((context or "No relevant verified facts or document excerpts found.") + held)
        if result and getattr(result, "has_evidence", False):
            note = f"{len(result.items)} source(s) will be sent"
            if result.needs_review_items:
                note += f" · {len(result.needs_review_items)} unverified fact(s) held back"
            self.ctx_evidence.setText(note)
        else:
            self.ctx_evidence.setText("No evidence found · general knowledge answer only · no personal claims will be made")

    def _update_context_preview(self) -> str:
        if not self.current_question:
            self.ctx_preview.clear()
            self.ctx_evidence.setText("No question · no context retrieved")
            return ""
        result = retrieve(self.store, self.current_question)
        context = build_context_string(result)
        self._render_retrieval(context, result)
        return context

    def get_context_for_question(self, question: str) -> str:
        if question.strip() == self.current_question and self.ctx_preview.toPlainText():
            result = retrieve(self.store, question)
            return build_context_string(result)
        result = retrieve(self.store, question)
        return build_context_string(result)
