"""Synchronous provider clients; call these from a background worker."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ai.prompt_builder import build_prompt


class ProviderError(RuntimeError):
    """A recoverable provider or configuration error."""


def _post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 90) -> dict:
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"The AI service returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ProviderError(f"Could not reach the AI service: {exc}. Check the connection and service settings, then try again.") from exc


def _get_env_key(key_name: str) -> str:
    """Fetch an API key from os.environ or directly from Windows User Registry if not yet loaded in process."""
    val = os.environ.get(key_name, "").strip()
    if val:
        return val
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            val, _ = winreg.QueryValueEx(k, key_name)
            if val:
                os.environ[key_name] = str(val).strip()
                return str(val).strip()
    except Exception:
        pass
    return ""


def _openrouter_client(base_url: str):
    """Lazy-import and return an OpenAI client configured for OpenRouter."""
    from openai import OpenAI

    api_key = _get_env_key("OPENROUTER_API_KEY")
    if not api_key:
        raise ProviderError(
            "OPENROUTER_API_KEY is not set. Add it to your Windows user environment and restart the app, "
            "or select Ollama for local-only use."
        )
    return OpenAI(
        base_url=base_url.rstrip("/") or "https://openrouter.ai/api/v1",
        api_key=api_key,
    )


def _groq_client(base_url: str):
    """Lazy-import and return an OpenAI client configured for Groq."""
    from openai import OpenAI

    api_key = _get_env_key("GROQ_API_KEY")
    if not api_key:
        raise ProviderError(
            "GROQ_API_KEY is not set. Add it to your Windows user environment and restart the app, "
            "or select Ollama for local-only use."
        )
    return OpenAI(
        base_url=base_url.rstrip("/") or "https://api.groq.com/openai/v1",
        api_key=api_key,
    )


def iter_ollama_response(prompt: str, model: str, ollama_url: str, max_tokens: int = 220):
    """Yield answer text as Ollama produces it."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": "30m",
        "options": {"num_ctx": 4096, "temperature": 0.55, "num_predict": max_tokens},
    }
    request = Request(
        f"{ollama_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                data = json.loads(line)
                piece = data.get("response") or ""
                if piece:
                    yield piece
                if data.get("done"):
                    break
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"The AI service returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ProviderError(f"Could not reach the AI service: {exc}. Check the connection and service settings, then try again.") from exc


def iter_openrouter_response(prompt: str, model: str, base_url: str, max_tokens: int = 700):
    """Yield answer text as OpenRouter produces it."""
    try:
        client = _openrouter_client(base_url)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Failed to initialize OpenRouter client: {exc}") from exc

    try:
        extra_body = {"reasoning": {"enabled": True}} if "nemotron" in model.lower() else None
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=max_tokens,
            stream=True,
            extra_body=extra_body,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"OpenRouter streaming request failed: {exc}") from exc


def iter_groq_response(prompt: str, model: str, base_url: str, max_tokens: int = 700):
    """Yield answer text as Groq produces it."""
    try:
        client = _groq_client(base_url)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Failed to initialize Groq client: {exc}") from exc

    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Groq streaming request failed: {exc}") from exc


def iter_provider_response(
    prompt: str,
    provider: str,
    model: str,
    ollama_url: str = "http://localhost:11434",
    openrouter_url: str = "https://openrouter.ai/api/v1",
    groq_url: str = "https://api.groq.com/openai/v1",
    max_tokens: int = 700,
):
    """Yield answer text incrementally across any configured provider."""
    if provider == "ollama":
        yield from iter_ollama_response(prompt, model, ollama_url, max_tokens=max_tokens)
    elif provider == "openrouter":
        yield from iter_openrouter_response(prompt, model, openrouter_url, max_tokens=max_tokens)
    elif provider == "groq":
        yield from iter_groq_response(prompt, model, groq_url, max_tokens=max_tokens)
    else:
        raise ProviderError(f"Unknown provider: {provider}")


def prewarm_ollama(model: str, ollama_url: str = "http://localhost:11434") -> bool:
    """Send a lightweight keep_alive request to ensure Ollama model is preloaded into VRAM/RAM."""
    try:
        _post_json(
            f"{ollama_url.rstrip('/')}/api/generate",
            {"model": model, "keep_alive": "30m"},
            timeout=5,
        )
        return True
    except Exception:
        return False


def iter_provider_response(
    prompt: str,
    provider: str,
    model: str,
    ollama_url: str = "http://localhost:11434",
    openrouter_url: str = "https://openrouter.ai/api/v1",
    groq_url: str = "https://api.groq.com/openai/v1",
    max_tokens: int = 340,
):
    """Stream answer tokens in real time from Ollama, Groq, or OpenRouter."""
    if provider == "ollama":
        yield from iter_ollama_response(prompt, model, ollama_url, max_tokens=max_tokens)
        return

    if provider in ("openrouter", "groq"):
        try:
            client = _openrouter_client(openrouter_url) if provider == "openrouter" else _groq_client(groq_url)
            kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.45,
                "max_tokens": max_tokens,
                "stream": True,
            }
            stream = client.chat.completions.create(**kwargs)
            yielded_any = False
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                delta = getattr(chunk.choices[0], "delta", None)
                piece = getattr(delta, "content", None) if delta else None
                if piece:
                    yielded_any = True
                    yield piece
            if yielded_any:
                return
        except ProviderError:
            raise
        except Exception:
            pass

    full = generate_from_prompt(
        prompt,
        provider,
        model,
        ollama_url=ollama_url,
        openrouter_url=openrouter_url,
        groq_url=groq_url,
        max_tokens=max_tokens,
    )
    if full:
        yield full


def generate_from_prompt(
    prompt: str,
    provider: str,
    model: str,
    ollama_url: str = "http://localhost:11434",
    openrouter_url: str = "https://openrouter.ai/api/v1",
    groq_url: str = "https://api.groq.com/openai/v1",
    max_tokens: int = 700,
) -> str:
    """Send one prompt to the selected provider."""
    if provider == "ollama":
        result = _post_json(
            f"{ollama_url.rstrip('/')}/api/generate",
            {"model": model, "prompt": prompt, "stream": False, "keep_alive": "30m", "options": {"num_ctx": 4096, "temperature": 0.55, "num_predict": max_tokens}},
        )
        answer = result.get("response", "").strip()
        if not answer:
            raise ProviderError("Ollama returned an empty answer. Confirm the model is available and try again.")
        return answer

    if provider == "openrouter":
        try:
            client = _openrouter_client(openrouter_url)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to initialize OpenRouter client: {exc}") from exc

        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=max_tokens,
                extra_body={"reasoning": {"enabled": True}},
            )
            choice = completion.choices[0]
            answer = (choice.message.content or "").strip()
            if not answer:
                raise ProviderError("OpenRouter returned an empty answer. Please try again.")
            return answer
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"OpenRouter request failed: {exc}. Check your API key and network connection.") from exc

    if provider == "groq":
        try:
            client = _groq_client(groq_url)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to initialize Groq client: {exc}") from exc

        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=max_tokens,
            )
            choice = completion.choices[0]
            answer = (choice.message.content or "").strip()
            if not answer:
                raise ProviderError("Groq returned an empty answer. Please try again.")
            return answer
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Groq request failed: {exc}. Check your API key and network connection.") from exc

    raise ProviderError(f"Unknown provider: {provider}")


def generate_answer(
    question: str,
    provider: str,
    model: str,
    style: str = "Balanced",
    ollama_url: str = "http://localhost:11434",
    context: str = "",
    openrouter_url: str = "https://openrouter.ai/api/v1",
    groq_url: str = "https://api.groq.com/openai/v1",
    tone: str = "",
    target_job_description: str = "",
) -> str:
    prompt = build_prompt(
        question,
        style,
        context=context,
        tone=tone,
        target_job_description=target_job_description,
    )
    return generate_from_prompt(
        prompt, provider, model, ollama_url, openrouter_url, groq_url
    )
