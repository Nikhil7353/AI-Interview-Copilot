"""Candidate profile editor dialog with verification-status tracking."""

from __future__ import annotations

from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.knowledge.profile import CandidateProfile, EducationEntry, EmploymentEntry, ProjectEntry, save_candidate_profile
from app.knowledge.store import KnowledgeStore
from app.ui.theme import APP_STYLESHEET, DIALOG_BACKDROP_STYLES
from app.windows.dwm_backdrop import apply_premium_window_chrome

STATUS_OPTIONS = ["Verified", "Needs review", "Unknown", "Outdated"]


class _NoWheelComboBox(QComboBox):
    """ComboBox that ignores mouse-wheel scrolling so scrolling the dialog does not accidentally change values."""

    def wheelEvent(self, event):
        event.ignore()


class ProfileEditor(QDialog):
    """Editable candidate profile. The user reviews extracted facts before they are used."""

    def __init__(self, store: KnowledgeStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Candidate profile · review before use")
        self.setMinimumWidth(720)
        self.setMinimumHeight(640)
        self.resize(760, 680)
        self.profile = CandidateProfile()
        self._build_ui()
        self._load_profile()
        self.setStyleSheet(APP_STYLESHEET + DIALOG_BACKDROP_STYLES)

    @staticmethod
    def _make_section(title_text: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("subCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        lbl = QLabel(title_text)
        lbl.setObjectName("sectionLabel")
        lay.addWidget(lbl)
        return card, lay

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        sheet = QFrame()
        sheet.setObjectName("glassSheet")
        layout = QVBoxLayout(sheet)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("Candidate profile")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.DemiBold))
        sub = QLabel("Review and edit extracted facts. Items marked Verified are injected into live interview prompts.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 8, 12)
        container_layout.setSpacing(12)

        # Candidate name
        name_group, name_layout = self._make_section("Candidate name")
        self.edit_full_name = QLineEdit()
        self.edit_full_name.setPlaceholderText("Your full name (e.g. John Smith)")
        name_layout.addWidget(self.edit_full_name)
        container_layout.addWidget(name_group)

        # Professional summary
        summary_group, summary_layout = self._make_section("Professional summary")
        self.edit_summary = QTextEdit()
        self.edit_summary.setPlaceholderText("Summarize your background in your own words…")
        self.edit_summary.setFixedHeight(88)
        summary_layout.addWidget(self.edit_summary)
        container_layout.addWidget(summary_group)

        # Skills
        skills_group, skills_layout = self._make_section("Skills and technologies")
        self.edit_skills = QTextEdit()
        self.edit_skills.setPlaceholderText("Python, Django, PostgreSQL, AWS, Docker (comma-separated or one per line)")
        self.edit_skills.setFixedHeight(82)
        skills_layout.addWidget(self.edit_skills)
        skill_status_row = QHBoxLayout()
        skill_status_row.addWidget(QLabel("Skills verification status:"))
        self.skill_status = _NoWheelComboBox()
        self.skill_status.addItems(STATUS_OPTIONS)
        skill_status_row.addWidget(self.skill_status, 1)
        skills_layout.addLayout(skill_status_row)
        container_layout.addWidget(skills_group)

        # Employment history
        emp_group, emp_layout = self._make_section("Employment history")
        self.edit_employment = QListWidget()
        self.edit_employment.setFixedHeight(110)
        self.edit_employment.setWordWrap(True)
        self.edit_employment.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        emp_layout.addWidget(self.edit_employment)
        emp_btns = QHBoxLayout()
        self.btn_emp_add = QPushButton("Add role")
        self.btn_emp_add.setObjectName("kbActionBtn")
        self.btn_emp_add.clicked.connect(self._add_employment)
        self.btn_emp_edit = QPushButton("Edit selected")
        self.btn_emp_edit.setObjectName("kbActionBtn")
        self.btn_emp_edit.clicked.connect(self._edit_employment)
        self.btn_emp_remove = QPushButton("Remove selected")
        self.btn_emp_remove.setObjectName("kbActionBtn")
        self.btn_emp_remove.clicked.connect(self._remove_selected_list)
        emp_btns.addWidget(self.btn_emp_add)
        emp_btns.addWidget(self.btn_emp_edit)
        emp_btns.addWidget(self.btn_emp_remove)
        emp_btns.addStretch()
        emp_layout.addLayout(emp_btns)
        container_layout.addWidget(emp_group)

        # Projects
        proj_group, proj_layout = self._make_section("Projects")
        self.edit_projects = QListWidget()
        self.edit_projects.setFixedHeight(105)
        self.edit_projects.setWordWrap(True)
        self.edit_projects.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        proj_layout.addWidget(self.edit_projects)
        proj_btns = QHBoxLayout()
        self.btn_proj_add = QPushButton("Add project")
        self.btn_proj_add.setObjectName("kbActionBtn")
        self.btn_proj_add.clicked.connect(self._add_project)
        self.btn_proj_edit = QPushButton("Edit selected")
        self.btn_proj_edit.setObjectName("kbActionBtn")
        self.btn_proj_edit.clicked.connect(self._edit_project)
        self.btn_proj_remove = QPushButton("Remove selected")
        self.btn_proj_remove.setObjectName("kbActionBtn")
        self.btn_proj_remove.clicked.connect(self._remove_selected_list)
        proj_btns.addWidget(self.btn_proj_add)
        proj_btns.addWidget(self.btn_proj_edit)
        proj_btns.addWidget(self.btn_proj_remove)
        proj_btns.addStretch()
        proj_layout.addLayout(proj_btns)
        container_layout.addWidget(proj_group)

        # Education & Certifications side-by-side
        edu_cert_row = QHBoxLayout()
        edu_cert_row.setSpacing(12)

        edu_group, edu_layout = self._make_section("Education")
        self.edit_education = QListWidget()
        self.edit_education.setFixedHeight(85)
        self.edit_education.setWordWrap(True)
        self.edit_education.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        edu_layout.addWidget(self.edit_education)
        edu_btns = QHBoxLayout()
        self.btn_edu_add = QPushButton("Add")
        self.btn_edu_add.setObjectName("kbActionBtn")
        self.btn_edu_add.clicked.connect(self._add_education)
        self.btn_edu_remove = QPushButton("Remove")
        self.btn_edu_remove.setObjectName("kbActionBtn")
        self.btn_edu_remove.clicked.connect(self._remove_selected_list)
        edu_btns.addWidget(self.btn_edu_add)
        edu_btns.addWidget(self.btn_edu_remove)
        edu_btns.addStretch()
        edu_layout.addLayout(edu_btns)
        edu_cert_row.addWidget(edu_group, 1)

        cert_group, cert_layout = self._make_section("Certifications")
        self.edit_certifications = QListWidget()
        self.edit_certifications.setFixedHeight(85)
        self.edit_certifications.setWordWrap(True)
        self.edit_certifications.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cert_layout.addWidget(self.edit_certifications)
        cert_btns = QHBoxLayout()
        self.btn_cert_add = QPushButton("Add")
        self.btn_cert_add.setObjectName("kbActionBtn")
        self.btn_cert_add.clicked.connect(self._add_certification)
        self.btn_cert_remove = QPushButton("Remove")
        self.btn_cert_remove.setObjectName("kbActionBtn")
        self.btn_cert_remove.clicked.connect(self._remove_selected_list)
        cert_btns.addWidget(self.btn_cert_add)
        cert_btns.addWidget(self.btn_cert_remove)
        cert_btns.addStretch()
        cert_layout.addLayout(cert_btns)
        edu_cert_row.addWidget(cert_group, 1)
        container_layout.addLayout(edu_cert_row)

        # Challenges & achievements
        chal_group, chal_layout = self._make_section("Technical challenges and achievements")
        chal_sub1 = QLabel("Technical challenges solved:")
        chal_sub1.setObjectName("muted")
        chal_layout.addWidget(chal_sub1)
        self.edit_challenges = QTextEdit()
        self.edit_challenges.setPlaceholderText("Challenges you solved, one per line…")
        self.edit_challenges.setFixedHeight(80)
        chal_layout.addWidget(self.edit_challenges)
        chal_sub2 = QLabel("Measurable achievements & metrics:")
        chal_sub2.setObjectName("muted")
        chal_layout.addWidget(chal_sub2)
        self.edit_achievements = QTextEdit()
        self.edit_achievements.setPlaceholderText("Measurable outcomes, one per line…")
        self.edit_achievements.setFixedHeight(80)
        chal_layout.addWidget(self.edit_achievements)
        container_layout.addWidget(chal_group)

        # Preferences & Overall Status
        pref_group, pref_outer = self._make_section("Answer preferences & verification status")
        pref_layout = QFormLayout()
        pref_layout.setSpacing(10)
        self.edit_length = _NoWheelComboBox()
        self.edit_length.addItems(["Short", "Balanced", "Detailed", "STAR"])
        self.edit_tone = _NoWheelComboBox()
        self.edit_tone.addItems(["Conversational", "Professional", "Direct"])
        self.status_overall = _NoWheelComboBox()
        self.status_overall.addItems(STATUS_OPTIONS)
        self.edit_target_jd = QTextEdit()
        self.edit_target_jd.setPlaceholderText("Paste the target job description here…")
        self.edit_target_jd.setFixedHeight(72)
        pref_layout.addRow("Answer length", self.edit_length)
        pref_layout.addRow("Tone", self.edit_tone)
        pref_layout.addRow("Overall profile status", self.status_overall)
        pref_layout.addRow("Target job description", self.edit_target_jd)
        pref_outer.addLayout(pref_layout)
        container_layout.addWidget(pref_group)

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        outer.addWidget(sheet)

    def _load_profile(self):
        data = self.store.get_full_profile()
        if not data:
            return
        self.profile = CandidateProfile.from_dict(data)
        self.edit_full_name.setText(self.profile.full_name)
        self.edit_summary.setPlainText(self.profile.professional_summary)
        self.edit_skills.setPlainText(", ".join(self.profile.skills))
        self.skill_status.setCurrentText(self._title_case(self.profile.skill_status))
        self._fill_list(self.edit_employment, self.profile.employment)
        self._fill_list(self.edit_projects, self.profile.projects)
        self._fill_list(self.edit_education, self.profile.education)
        self._fill_list(self.edit_certifications, self.profile.certifications)
        self.edit_challenges.setPlainText("\n".join(self.profile.technical_challenges))
        self.edit_achievements.setPlainText("\n".join(self.profile.achievements))
        self.edit_length.setCurrentText(self.profile.preferred_answer_length)
        self.edit_tone.setCurrentText(self.profile.preferred_tone)
        self.edit_target_jd.setPlainText(self.profile.target_job_description)
        self.status_overall.setCurrentText(self._title_case(self.profile.overall_status))

    @staticmethod
    def _title_case(value: str) -> str:
        return " ".join(w.capitalize() for w in value.split())

    @staticmethod
    def _snake_case(value: str) -> str:
        return value.strip().lower().replace(" ", "_")

    def _fill_list(self, list_widget: QListWidget, entries: list):
        list_widget.clear()
        for entry in entries:
            if isinstance(entry, EmploymentEntry):
                dates = f" ({entry.start_date} – {entry.end_date})" if (entry.start_date or entry.end_date) else ""
                text = f"💼  {entry.title} at {entry.company}{dates}"
            elif isinstance(entry, ProjectEntry):
                desc = f" — {entry.description}" if entry.description else ""
                text = f"🚀  {entry.name}{desc}"
            elif isinstance(entry, EducationEntry):
                text = f"🎓  {entry.degree} · {entry.institution}"
            else:
                text = f"📜  {getattr(entry, 'name', None) or str(entry)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            list_widget.addItem(item)

    def _current_item_data(self, list_widget: QListWidget):
        item = list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _remove_selected_list(self):
        sender = self.sender()
        mapping = {
            self.btn_emp_remove: self.edit_employment,
            self.btn_proj_remove: self.edit_projects,
            self.btn_edu_remove: self.edit_education,
            self.btn_cert_remove: self.edit_certifications,
        }
        lw = mapping.get(sender)
        if lw is None:
            return
        row = lw.currentRow()
        if row < 0:
            return
        lw.takeItem(row)
        if lw is self.edit_employment and row < len(self.profile.employment):
            self.profile.employment.pop(row)
        elif lw is self.edit_projects and row < len(self.profile.projects):
            self.profile.projects.pop(row)
        elif lw is self.edit_education and row < len(self.profile.education):
            self.profile.education.pop(row)
        elif lw is self.edit_certifications and row < len(self.profile.certifications):
            self.profile.certifications.pop(row)

    def _add_employment(self):
        dlg = _EntryDialog("Add employment role", ["Title", "Company", "Start date", "End date", "Responsibilities (comma-separated)"], self)
        if dlg.exec():
            values = dlg.values()
            entry = EmploymentEntry(
                title=values[0], company=values[1], start_date=values[2], end_date=values[3],
                responsibilities=[v.strip() for v in values[4].split(",") if v.strip()],
                status="needs_review",
            )
            self.profile.employment.append(entry)
            self._fill_list(self.edit_employment, self.profile.employment)

    def _edit_employment(self):
        row = self.edit_employment.currentRow()
        if row < 0:
            return
        entry = self.profile.employment[row]
        dlg = _EntryDialog("Edit employment role", ["Title", "Company", "Start date", "End date", "Responsibilities (comma-separated)"], self,
                           values=[entry.title, entry.company, entry.start_date, entry.end_date, ", ".join(entry.responsibilities)])
        if dlg.exec():
            values = dlg.values()
            self.profile.employment[row] = EmploymentEntry(
                title=values[0], company=values[1], start_date=values[2], end_date=values[3],
                responsibilities=[v.strip() for v in values[4].split(",") if v.strip()],
                status=entry.status,
            )
            self._fill_list(self.edit_employment, self.profile.employment)
            self.edit_employment.setCurrentRow(row)

    def _add_project(self):
        dlg = _EntryDialog("Add project", ["Project name", "Description", "Technologies (comma-separated)", "Your role", "Achievements (comma-separated)"], self)
        if dlg.exec():
            values = dlg.values()
            entry = ProjectEntry(
                name=values[0], description=values[1],
                technologies=[v.strip() for v in values[2].split(",") if v.strip()],
                role=values[3],
                achievements=[v.strip() for v in values[4].split(",") if v.strip()],
                status="needs_review",
            )
            self.profile.projects.append(entry)
            self._fill_list(self.edit_projects, self.profile.projects)

    def _edit_project(self):
        row = self.edit_projects.currentRow()
        if row < 0:
            return
        entry = self.profile.projects[row]
        dlg = _EntryDialog("Edit project", ["Project name", "Description", "Technologies (comma-separated)", "Your role", "Achievements (comma-separated)"], self,
                           values=[entry.name, entry.description, ", ".join(entry.technologies), entry.role, ", ".join(entry.achievements)])
        if dlg.exec():
            values = dlg.values()
            self.profile.projects[row] = ProjectEntry(
                name=values[0], description=values[1],
                technologies=[v.strip() for v in values[2].split(",") if v.strip()],
                role=values[3],
                achievements=[v.strip() for v in values[4].split(",") if v.strip()],
                status=entry.status,
            )
            self._fill_list(self.edit_projects, self.profile.projects)
            self.edit_projects.setCurrentRow(row)

    def _add_education(self):
        dlg = _EntryDialog("Add education", ["Degree", "Institution", "Field of study", "Graduation date"], self)
        if dlg.exec():
            values = dlg.values()
            from app.knowledge.profile import EducationEntry
            entry = EducationEntry(degree=values[0], institution=values[1], field_of_study=values[2], graduation_date=values[3])
            self.profile.education.append(entry)
            self._fill_list(self.edit_education, self.profile.education)

    def _add_certification(self):
        dlg = _EntryDialog("Add certification", ["Certification name", "Issuer", "Date"], self)
        if dlg.exec():
            values = dlg.values()
            from app.knowledge.profile import CertificationEntry
            entry = CertificationEntry(name=values[0], issuer=values[1], date=values[2])
            self.profile.certifications.append(entry)
            self._fill_list(self.edit_certifications, self.profile.certifications)

    def _save(self):
        self.profile.full_name = self.edit_full_name.text().strip()
        self.profile.professional_summary = self.edit_summary.toPlainText().strip()
        self.profile.skills = [
            part.strip()
            for part in self.edit_skills.toPlainText().replace(",", "\n").splitlines()
            if part.strip()
        ]
        self.profile.skill_status = self._snake_case(self.skill_status.currentText())
        self.profile.preferred_answer_length = self.edit_length.currentText()
        self.profile.preferred_tone = self.edit_tone.currentText()
        self.profile.target_job_description = self.edit_target_jd.toPlainText().strip()
        self.profile.technical_challenges = [s.strip() for s in self.edit_challenges.toPlainText().splitlines() if s.strip()]
        self.profile.achievements = [s.strip() for s in self.edit_achievements.toPlainText().splitlines() if s.strip()]
        self.profile.overall_status = self._snake_case(self.status_overall.currentText())

        if self.profile.overall_status == "verified":
            for entry in self.profile.employment:
                entry.status = "verified"
            for entry in self.profile.projects:
                entry.status = "verified"
            for entry in self.profile.education:
                entry.status = "verified"
            for entry in self.profile.certifications:
                entry.status = "verified"

        save_candidate_profile(self.store, self.profile)
        self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        apply_premium_window_chrome(self, dialog=True)


class _EntryDialog(QDialog):
    def __init__(self, title, labels, parent=None, values=None, status: str = "needs_review"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        sheet = QFrame()
        sheet.setObjectName("glassSheet")
        layout = QVBoxLayout(sheet)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("sectionLabel")
        layout.addWidget(heading)
        self.inputs = []
        form = QFormLayout()
        form.setSpacing(10)
        for i, label in enumerate(labels):
            edit = QTextEdit() if len(label) > 20 else QLineEdit()
            if isinstance(edit, QTextEdit):
                edit.setMaximumHeight(68)
            if values and i < len(values):
                edit.setText(values[i])
            form.addRow(label, edit)
            self.inputs.append(edit)

        self.status_combo = QComboBox()
        self.status_combo.addItems(STATUS_OPTIONS)
        status_norm = " ".join(w.capitalize() for w in status.replace("-", " ").split("_"))
        self.status_combo.setCurrentText(status_norm if status_norm in STATUS_OPTIONS else "Needs review")
        form.addRow("Verification status", self.status_combo)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        outer.addWidget(sheet)
        self.setStyleSheet(APP_STYLESHEET + DIALOG_BACKDROP_STYLES)

    def showEvent(self, event):
        super().showEvent(event)
        apply_premium_window_chrome(self, dialog=True)

    def values(self):
        return [inp.toPlainText().strip() if isinstance(inp, QTextEdit) else inp.text().strip() for inp in self.inputs]

    def status_value(self) -> str:
        return self.status_combo.currentText().strip().lower().replace(" ", "_")
