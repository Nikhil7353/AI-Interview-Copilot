from PySide6.QtCore import QObject, Signal, Slot

from app.ai.prompt_builder import build_prompt
from app.ai.providers import ProviderError, generate_answer, iter_ollama_response, iter_provider_response


class AnswerWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    partial = Signal(str)
    context_loaded = Signal(str, object)

    def __init__(
        self,
        question: str,
        provider: str,
        model: str,
        style: str,
        ollama_url: str,
        context: str = "",
        openrouter_url: str = "https://openrouter.ai/api/v1",
        groq_url: str = "https://api.groq.com/openai/v1",
        store=None,
        tone: str = "",
        target_job_description: str = "",
    ):
        super().__init__()
        self.args = (question, provider, model, style, ollama_url, context, openrouter_url, groq_url)
        self.store = store
        self.tone = tone
        self.target_job_description = target_job_description

    @Slot()
    def run(self):
        try:
            question, provider, model, style, ollama_url, context, openrouter_url, groq_url = self.args
            tone = self.tone
            target_jd = self.target_job_description
            if self.store is not None and not context:
                from app.knowledge.retrieval import build_context_string, retrieve

                retrieval = retrieve(self.store, question)
                context = build_context_string(retrieval)
                candidate_name = ""
                try:
                    profile = self.store.get_full_profile() or {}
                    candidate_name = str(profile.get("full_name") or "")
                    tone = tone or str(profile.get("preferred_tone") or "")
                    target_jd = target_jd or str(profile.get("target_job_description") or "")
                except Exception:
                    pass
                self.context_loaded.emit(context, retrieval)

            if provider == "ollama":
                prompt = build_prompt(
                    question,
                    style,
                    context=context,
                    tone=tone,
                    target_job_description=target_jd,
                    candidate_name=candidate_name,
                )
                parts: list[str] = []
                for piece in iter_ollama_response(prompt, model, ollama_url, max_tokens=320):
                    parts.append(piece)
                    self.partial.emit("".join(parts))
                answer = "".join(parts).strip()
                if not answer:
                    raise ProviderError("Ollama returned an empty answer. Confirm the model is available and try again.")
                self.finished.emit(answer)
                return

            if provider in ("groq", "openrouter"):
                prompt = build_prompt(
                    question,
                    style,
                    context=context,
                    tone=tone,
                    target_job_description=target_jd,
                    candidate_name=candidate_name,
                )
                parts = []
                for piece in iter_provider_response(
                    prompt,
                    provider,
                    model,
                    ollama_url=ollama_url,
                    openrouter_url=openrouter_url,
                    groq_url=groq_url,
                    max_tokens=360,
                ):
                    parts.append(piece)
                    self.partial.emit("".join(parts))
                answer = "".join(parts).strip()
                if not answer:
                    raise ProviderError(f"{provider.title()} returned an empty answer.")
                self.finished.emit(answer)
                return
            self.finished.emit(
                generate_answer(
                    question,
                    provider,
                    model,
                    style,
                    ollama_url,
                    context,
                    openrouter_url,
                    groq_url,
                    tone=tone,
                    target_job_description=target_jd,
                )
            )
        except ProviderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # keep an unexpected provider failure out of the UI event loop
            self.failed.emit(f"Unexpected error: {exc}")
