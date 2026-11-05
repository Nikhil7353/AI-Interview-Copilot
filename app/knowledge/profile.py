"""Candidate profile model, generic resume section parser, and verification-status tracking."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EmploymentEntry:
    title: str = ""
    company: str = ""
    start_date: str = ""
    end_date: str = ""
    responsibilities: list[str] = field(default_factory=list)
    status: str = "needs_review"


@dataclass
class ProjectEntry:
    name: str = ""
    description: str = ""
    technologies: list[str] = field(default_factory=list)
    role: str = ""
    achievements: list[str] = field(default_factory=list)
    status: str = "needs_review"


@dataclass
class EducationEntry:
    degree: str = ""
    institution: str = ""
    field_of_study: str = ""
    graduation_date: str = ""
    status: str = "needs_review"


@dataclass
class CertificationEntry:
    name: str = ""
    issuer: str = ""
    date: str = ""
    status: str = "needs_review"


@dataclass
class CandidateProfile:
    full_name: str = ""
    professional_summary: str = ""
    skills: list[str] = field(default_factory=list)
    skill_status: str = "needs_review"
    employment: list[EmploymentEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    certifications: list[CertificationEntry] = field(default_factory=list)
    technical_challenges: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    preferred_answer_length: str = "Balanced"
    preferred_tone: str = "Conversational"
    target_job_description: str = ""
    overall_status: str = "needs_review"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateProfile":
        employment = [
            EmploymentEntry(**e) if isinstance(e, dict) else EmploymentEntry(title=str(e))
            for e in data.get("employment", [])
        ]
        projects = [
            ProjectEntry(**p) if isinstance(p, dict) else ProjectEntry(name=str(p))
            for p in data.get("projects", [])
        ]
        education = [
            EducationEntry(**edu) if isinstance(edu, dict) else EducationEntry(degree=str(edu))
            for edu in data.get("education", [])
        ]
        certifications = [
            CertificationEntry(**c) if isinstance(c, dict) else CertificationEntry(name=str(c))
            for c in data.get("certifications", [])
        ]
        return cls(
            full_name=data.get("full_name", ""),
            professional_summary=data.get("professional_summary", ""),
            skills=data.get("skills", []),
            skill_status=data.get("skill_status", "needs_review"),
            employment=employment,
            projects=projects,
            education=education,
            certifications=certifications,
            technical_challenges=data.get("technical_challenges", []),
            achievements=data.get("achievements", []),
            preferred_answer_length=data.get("preferred_answer_length", "Balanced"),
            preferred_tone=data.get("preferred_tone", "Conversational"),
            target_job_description=data.get("target_job_description", ""),
            overall_status=data.get("overall_status", "needs_review"),
        )

    def has_verified_experience(self) -> bool:
        for e in self.employment:
            if e.status == "verified":
                return True
        for p in self.projects:
            if p.status == "verified":
                return True
        return False

    def verified_skills(self) -> list[str]:
        return self.skills if self.skill_status == "verified" else []

    def missing_personal_evidence(self) -> list[str]:
        missing: list[str] = []
        if not self.has_verified_experience():
            missing.append("employment or project experience")
        if self.skill_status != "verified" and not self.skills:
            missing.append("technical skills")
        if not self.professional_summary:
            missing.append("professional summary")
        return missing


# Section header patterns for generic resume parsing
_SECTION_HEADERS: dict[str, tuple[str, ...]] = {
    "summary": ("SUMMARY", "PROFESSIONAL SUMMARY", "PROFILE", "ABOUT ME", "OBJECTIVE", "CAREER SUMMARY"),
    "skills": ("TECHNICAL SKILLS", "SKILLS", "CORE COMPETENCIES", "TECHNOLOGIES", "SKILLS & TECHNOLOGIES"),
    "experience": ("WORK EXPERIENCE", "EXPERIENCE", "PROFESSIONAL EXPERIENCE", "EMPLOYMENT HISTORY", "INTERNSHIPS"),
    "projects": ("PROJECTS", "KEY PROJECTS", "ACADEMIC PROJECTS", "PERSONAL PROJECTS"),
    "education": ("EDUCATION", "ACADEMIC BACKGROUND", "QUALIFICATIONS"),
    "certifications": ("COURSES AND CERTIFICATIONS", "CERTIFICATIONS", "COURSES", "CERTIFICATES", "LICENSES & CERTIFICATIONS"),
}

_DATE_SPAN_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\b(?:19|20)\d{2}\b)"
    r"\s*[–\-—to]+\s*"
    r"(Present|Current|Now|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\b(?:19|20)\d{2}\b)",
    re.IGNORECASE,
)


def _detect_section(line: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z &/]", "", line).strip().upper()
    if not cleaned or len(cleaned) > 42:
        return None
    for sec_key, headers in _SECTION_HEADERS.items():
        if cleaned in headers:
            return sec_key
    return None


def _merge_wrapped_lines(lines: list[str]) -> list[str]:
    """Join PDF lines that were hard-wrapped mid-sentence while keeping headers, roles, and bullets distinct."""
    out: list[str] = []
    for raw in lines:
        ln = re.sub(r"\s+", " ", raw).strip()
        if not ln:
            continue
        is_bullet = raw.lstrip().startswith(("•", "-", "*", "▪"))
        has_date = bool(_DATE_SPAN_RE.search(ln))
        is_header = _detect_section(ln) is not None
        is_label_line = ":" in ln[:32] and not is_bullet
        if is_bullet:
            out.append("• " + ln.lstrip("•-*▪ ").strip())
        elif is_header or has_date or is_label_line or " — " in ln or " | " in ln:
            out.append(ln)
        elif out and out[-1].startswith("• "):
            out[-1] = out[-1] + " " + ln
        else:
            out.append(ln)
    return out


_FALLBACK_SKILL_TOKENS = (
    "Python", "Django REST Framework", "Django", "FastAPI", "Flask",
    "React.js", "React", "TypeScript", "JavaScript", "PostgreSQL", "MySQL", "SQL",
    "Docker", "Kubernetes", "GitHub Actions", "CI/CD", "Pytest", "Redis", "Celery",
    "Django Channels", "WebSockets", "Tailwind CSS", "AWS", "JWT", "REST API",
    "Git", "Tesseract OCR", "OpenCV", "Razorpay",
)


def _parse_skills_section(lines: list[str], full_text: str) -> list[str]:
    skills: list[str] = []
    ignore_categories = {"languages known", "spoken languages", "hobbies", "interests"}
    for ln in lines:
        clean = ln.lstrip("•-* ").strip()
        if ":" in clean:
            cat, rest = clean.split(":", 1)
            if cat.strip().lower() in ignore_categories:
                continue
            clean = rest
        # Split on commas, bullets, pipes, or em-dashes
        for part in re.split(r"[,|•;]", clean):
            tok = part.strip()
            tok = re.sub(r"\s*\((?:fundamentals|basic|beginner).*?\)", "", tok, flags=re.IGNORECASE).strip()
            if "—" in tok:
                subparts = [p.strip() for p in tok.split("—") if p.strip()]
                for sp in subparts:
                    if 1 < len(sp) <= 38 and sp not in skills:
                        skills.append(sp)
                continue
            if 1 < len(tok) <= 38 and tok not in skills:
                skills.append(tok)
    if not skills:
        lower_full = full_text.lower()
        for token in _FALLBACK_SKILL_TOKENS:
            if token.lower() in lower_full and token not in skills:
                skills.append(token)
    return skills[:40]


def extract_profile_from_resume_text(text: str, status: str = "verified") -> CandidateProfile:
    """Parse any resume text into structured sections (Summary, Skills, Experience, Projects, Education, Certifications)."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = [ln.strip() for ln in normalized.splitlines() if ln.strip()]

    sections: dict[str, list[str]] = {
        "header": [],
        "summary": [],
        "skills": [],
        "experience": [],
        "projects": [],
        "education": [],
        "certifications": [],
    }
    current_sec = "header"
    for ln in raw_lines:
        sec = _detect_section(ln)
        if sec is not None:
            current_sec = sec
            continue
        sections[current_sec].append(ln)

    # 1. Summary
    summary_lines = _merge_wrapped_lines(sections["summary"])
    summary = " ".join(ln.lstrip("• ") for ln in summary_lines).strip()
    if not summary and len(sections["header"]) >= 2:
        summary = " ".join(sections["header"][1:3]).strip()

    # 2. Skills
    skills = _parse_skills_section(_merge_wrapped_lines(sections["skills"]), normalized)

    # 3. Experience & Embedded Projects
    employment: list[EmploymentEntry] = []
    projects: list[ProjectEntry] = []
    exp_raw = sections["experience"]

    # First pass on raw experience lines to merge date-only continuation lines onto the preceding role line
    exp_lines: list[str] = []
    idx = 0
    while idx < len(exp_raw):
        cur = re.sub(r"\s+", " ", exp_raw[idx]).strip()
        if idx + 1 < len(exp_raw):
            nxt = re.sub(r"\s+", " ", exp_raw[idx + 1]).strip()
            if _DATE_SPAN_RE.fullmatch(nxt) and not _DATE_SPAN_RE.search(cur):
                cur = f"{cur}  {nxt}"
                idx += 2
                exp_lines.append(cur)
                continue
        exp_lines.append(cur)
        idx += 1
    exp_lines = _merge_wrapped_lines(exp_lines)

    current_role: EmploymentEntry | None = None
    current_project_name = ""
    current_project_tech: list[str] = []

    for ln in exp_lines:
        if ln.startswith("• "):
            bullet_text = ln[2:].strip()
            if current_role is not None:
                current_role.responsibilities.append(bullet_text)
            continue

        if ln.lower().startswith("tech stack:"):
            tech_raw = ln.split(":", 1)[1]
            current_project_tech = [t.strip() for t in tech_raw.split(",") if t.strip()]
            continue

        date_match = _DATE_SPAN_RE.search(ln)
        if (" — " in ln or " - " in ln or date_match) and not ln.startswith("•"):
            start_d = date_match.group(1).strip() if date_match else ""
            end_d = date_match.group(2).strip() if date_match else ""
            line_wo_date = ln[: date_match.start()].strip() if date_match else ln
            if " — " in line_wo_date:
                left, right = line_wo_date.split(" — ", 1)
            elif " - " in line_wo_date:
                left, right = line_wo_date.split(" - ", 1)
            else:
                left, right = line_wo_date, ""

            if current_role is not None and current_project_name:
                projects.append(
                    ProjectEntry(
                        name=current_project_name,
                        description="; ".join(current_role.responsibilities[:2]),
                        technologies=current_project_tech or skills[:10],
                        role=current_role.title,
                        achievements=[b for b in current_role.responsibilities if "%" in b or "140+" in b][:4] or current_role.responsibilities[:3],
                        status=status,
                    )
                )
                current_project_name = ""
                current_project_tech = []

            current_role = EmploymentEntry(
                title=left.strip(),
                company=right.strip(),
                start_date=start_d,
                end_date=end_d,
                responsibilities=[],
                status=status,
            )
            employment.append(current_role)
        elif current_role is not None and not current_role.responsibilities and ("|" in ln or "platform" in ln.lower() or "system" in ln.lower()):
            current_project_name = ln.split("|")[0].strip()

    if current_role is not None and current_project_name:
        projects.append(
            ProjectEntry(
                name=current_project_name,
                description="; ".join(current_role.responsibilities[:2]),
                technologies=current_project_tech or skills[:10],
                role=current_role.title,
                achievements=[b for b in current_role.responsibilities if "%" in b or "140+" in b][:4] or current_role.responsibilities[:3],
                status=status,
            )
        )

    # 4. Explicit Projects section (if resume has a separate PROJECTS header)
    proj_lines = _merge_wrapped_lines(sections["projects"])
    active_proj: ProjectEntry | None = None
    for ln in proj_lines:
        if ln.startswith("• "):
            b = ln[2:].strip()
            if active_proj is not None:
                active_proj.achievements.append(b)
                if not active_proj.description:
                    active_proj.description = b
        else:
            active_proj = ProjectEntry(
                name=ln.split("|")[0].split("—")[0].strip(),
                description="",
                technologies=skills[:8],
                role="Developer",
                achievements=[],
                status=status,
            )
            projects.append(active_proj)

    # 5. Education (merge date-only lines onto preceding degree line before pairing with institution)
    education: list[EducationEntry] = []
    edu_raw = sections["education"]
    edu_merged: list[str] = []
    idx = 0
    while idx < len(edu_raw):
        cur = re.sub(r"\s+", " ", edu_raw[idx]).strip()
        if idx + 1 < len(edu_raw):
            nxt = re.sub(r"\s+", " ", edu_raw[idx + 1]).strip()
            if _DATE_SPAN_RE.fullmatch(nxt) and not _DATE_SPAN_RE.search(cur):
                cur = f"{cur}  {nxt}"
                idx += 2
                edu_merged.append(cur)
                continue
        edu_merged.append(cur)
        idx += 1
    edu_lines = _merge_wrapped_lines(edu_merged)
    i = 0
    while i < len(edu_lines):
        ln = edu_lines[i]
        dm = _DATE_SPAN_RE.search(ln)
        grad = f"{dm.group(1)} – {dm.group(2)}" if dm else ""
        deg = ln[: dm.start()].strip() if dm else ln
        inst = edu_lines[i + 1] if i + 1 < len(edu_lines) and not _DATE_SPAN_RE.search(edu_lines[i + 1]) else ""
        field_study = "Computer Science" if "computer science" in deg.lower() else ""
        if deg:
            education.append(
                EducationEntry(
                    degree=deg,
                    institution=inst.split("|")[0].strip() if inst else "",
                    field_of_study=field_study,
                    graduation_date=grad,
                    status=status,
                )
            )
        i += 2 if inst else 1

    # 6. Certifications
    certifications: list[CertificationEntry] = []
    for ln in _merge_wrapped_lines(sections["certifications"]):
        clean = ln.lstrip("•-* ").replace("🔗", "").strip()
        if not clean:
            continue
        if " — " in clean:
            issuer, cname = clean.split(" — ", 1)
            certifications.append(CertificationEntry(name=cname.strip(), issuer=issuer.strip(), date="", status=status))
        else:
            certifications.append(CertificationEntry(name=clean, issuer="", date="", status=status))

    # 7. Challenges & Achievements across all experience bullets
    challenges: list[str] = []
    achievements: list[str] = []
    for role in employment:
        for b in role.responsibilities:
            if any(tok in b.lower() for tok in ("%", "140+", "reduced", "improved", "delivered")):
                if b not in achievements:
                    achievements.append(b)
            else:
                if b not in challenges:
                    challenges.append(b)

    return CandidateProfile(
        professional_summary=summary,
        skills=skills,
        skill_status=status,
        employment=employment,
        projects=projects,
        education=education,
        certifications=certifications,
        technical_challenges=challenges[:6],
        achievements=achievements[:6],
        preferred_answer_length="Balanced",
        preferred_tone="Conversational",
        target_job_description="",
        overall_status=status,
    )


def save_candidate_profile(store, profile: CandidateProfile) -> None:
    """Persist a CandidateProfile and its retrieval facts into KnowledgeStore."""
    store.clear_profile()
    store.set_profile_field("full_name", profile.full_name, profile.overall_status, "user_profile")
    if profile.full_name:
        store.add_profile_fact("identity", f"Candidate Name: {profile.full_name}", "verified", "user_profile")
    store.set_profile_field("professional_summary", profile.professional_summary, profile.overall_status, "user_profile")
    store.set_profile_field("skills", profile.skills, profile.skill_status, "user_profile")
    store.set_profile_field("preferred_answer_length", profile.preferred_answer_length, profile.overall_status, "user_profile")
    store.set_profile_field("preferred_tone", profile.preferred_tone, profile.overall_status, "user_profile")
    store.set_profile_field("target_job_description", profile.target_job_description, profile.overall_status, "user_profile")
    store.set_profile_field("technical_challenges", profile.technical_challenges, profile.overall_status, "user_profile")
    store.set_profile_field("achievements", profile.achievements, profile.overall_status, "user_profile")
    store.set_profile_field("overall_status", profile.overall_status, profile.overall_status, "user_profile")
    store.set_profile_field("employment", [asdict(entry) for entry in profile.employment], profile.overall_status, "user_profile")
    store.set_profile_field("projects", [asdict(entry) for entry in profile.projects], profile.overall_status, "user_profile")
    store.set_profile_field("education", [asdict(entry) for entry in profile.education], profile.overall_status, "user_profile")
    store.set_profile_field("certifications", [asdict(entry) for entry in profile.certifications], profile.overall_status, "user_profile")

    if profile.professional_summary:
        store.add_profile_fact("summary", profile.professional_summary, profile.overall_status, "user_profile")
    for entry in profile.employment:
        dates = f" ({entry.start_date} – {entry.end_date})" if (entry.start_date or entry.end_date) else ""
        store.add_profile_fact(
            "experience",
            f"{entry.title} at {entry.company}{dates}: " + "; ".join(entry.responsibilities),
            entry.status,
            "user_profile",
        )
    for entry in profile.projects:
        store.add_profile_fact(
            "projects",
            f"{entry.name} ({entry.role}): {entry.description}. Tech: {', '.join(entry.technologies)}. Key results: {'; '.join(entry.achievements)}",
            entry.status,
            "user_profile",
        )
    for entry in profile.education:
        store.add_profile_fact(
            "education",
            f"{entry.degree} at {entry.institution} ({entry.graduation_date})",
            entry.status,
            "user_profile",
        )
    for entry in profile.certifications:
        issuer_str = f" — {entry.issuer}" if entry.issuer else ""
        store.add_profile_fact(
            "certifications",
            f"{entry.name}{issuer_str}",
            entry.status,
            "user_profile",
        )
    if profile.skills:
        store.add_profile_fact("skills", "Technical Skills: " + ", ".join(profile.skills), profile.skill_status, "user_profile")
    for chal in profile.technical_challenges:
        store.add_profile_fact("challenges", chal, profile.overall_status, "user_profile")
    for ach in profile.achievements:
        store.add_profile_fact("achievements", ach, profile.overall_status, "user_profile")
