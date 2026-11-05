"""Build interview answers with explicit evidence boundaries and natural human speech."""

from __future__ import annotations


def build_prompt(
    question: str,
    style: str = "Balanced",
    context: str = "",
    tone: str = "",
    target_job_description: str = "",
    candidate_name: str = "",
) -> str:
    context_block = f"\nVerified context (use only if relevant):\n{context.strip()}\n" if context.strip() else ""
    tone_note = f" Tone: {tone.strip().lower()}." if tone and tone.strip() else ""
    jd_note = (
        f"\nTarget role context (align emphasis where truthful):\n{target_job_description.strip()[:600]}\n"
        if target_job_description and target_job_description.strip()
        else ""
    )
    style_instructions = {
        "Short": (
            "Format as 2–3 short, punchy bullet points (• ). "
            "Keep each point under 18 words so it can be spoken in a single breath."
        ),
        "Balanced": (
            "Format as 3–4 natural conversational bullet points (• ). "
            "Each bullet must be 1–2 direct spoken sentences explaining what we built, the technical choice, and why."
        ),
        "Detailed": (
            "Format as 4–5 conversational bullet points (• ) covering architecture, design trade-offs, and production edge cases."
        ),
        "STAR": (
            "Format as 3–4 conversational bullet points following a natural story arc (Context -> Problem -> What I built & why -> Impact/Result). "
            "Do NOT write the labels 'Situation:', 'Task:', 'Action:', or 'Result:' — weave the story naturally."
        ),
    }.get(style, "Format as 3–4 natural, conversational spoken bullet points (• ).")

    name_instruction = (
        f"You are helping software engineer {candidate_name} answer an interview question out loud.\n"
        if candidate_name
        else "You are helping a software engineer answer an interview question out loud.\n"
    )

    return (
        f"{name_instruction}"
        "Write strictly what the candidate speaks in a real, natural, confident conversation with a tech lead.\n\n"
        "STRICT HUMAN-SPEECH RULES:\n"
        "- Sound like a real senior software engineer explaining their actual codebase over coffee, NOT like a textbook, AI assistant, or written essay.\n"
        "- Never use robotic AI buzzwords like 'orchestrate', 'leverage', 'delve', 'pivotal', 'testament', 'seamlessly', 'robust', 'optimal efficiency', 'holistic', or 'in order to'.\n"
        "- Never write out rigid labels like 'Situation:', 'Task:', 'Action:', or 'Result:'. Tell the story naturally.\n"
        "- Important: do not invent personal experience, projects, metrics, employers, decisions, or placeholder names like 'John Doe'.\n"
        "- Use natural conversational openers and transitions: 'Basically...', 'In our platform...', 'What we did was...', 'The tricky part was...', 'Here\\'s how we handled that...'.\n"
        "- Keep sentences short, punchy, and conversational with natural contractions ('we\\'ve', 'didn\\'t', 'wasn\\'t', 'here\\'s why').\n"
        "- Never make up placeholder names like 'John Doe'. If asked for your name, use the candidate's real name or introduce yourself directly by role.\n"
        "- Never start with 'Certainly', 'Great question', 'As an AI', or robotic starters like 'I would start by...'. Jump straight into the spoken answer.\n"
        "- Ground the answer in verified details from the notes. If a question asks about personal experience and no verified context supports it, answer the technical concept in general terms and do not pretend it was your project.\n\n"
        f"Answer style: {style}. {style_instructions}\n"
        f"{tone_note}{jd_note}{context_block}\nQuestion:\n{question.strip()}\n\nSpoken answer:"
    )

