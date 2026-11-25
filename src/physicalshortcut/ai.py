"""Appel d'une IA (API compatible OpenAI : Ollama, LM Studio, OpenAI, OpenRouter...).

Utilise pour :
* l'etape ``ai_ask`` d'un workflow (poser une question, avec ou sans l'image de la camera) ;
* la reconnaissance de dessins en mode ``ai`` / ``auto`` (envoi du trace en PNG).

Rien n'est envoye sans configuration : aucun modele, aucun appel. La cle d'API n'est jamais
stockee : on enregistre seulement le NOM de la variable d'environnement qui la contient.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from . import settings

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"  # Ollama
MAX_RESPONSE_BYTES = 2_000_000


class AIError(RuntimeError):
    """Erreur d'appel a l'IA ; message affichable."""


def resolve(base_url: str = "", model: str = "", key_env: str = "") -> dict[str, str]:
    cfg = settings.current()
    url = (base_url or cfg.get("ai_base_url") or os.environ.get("PHYSICALSHORTCUT_AI_URL") or DEFAULT_BASE_URL).strip()
    name = (model or cfg.get("ai_model") or os.environ.get("PHYSICALSHORTCUT_AI_MODEL") or "").strip()
    env_name = (key_env or cfg.get("ai_key_env") or "PHYSICALSHORTCUT_AI_KEY").strip()
    return {"base_url": url.rstrip("/"), "model": name, "key": os.environ.get(env_name, "")}


def is_configured() -> bool:
    return bool(resolve()["model"])


def ask(
    prompt: str,
    *,
    system: str = "",
    image: bytes | None = None,
    image_mime: str = "image/jpeg",
    base_url: str = "",
    model: str = "",
    key_env: str = "",
    timeout: float = 60.0,
    max_tokens: int = 300,
) -> str:
    conf = resolve(base_url, model, key_env)
    if not conf["model"]:
        raise AIError("Aucun modèle IA configuré (Activité > Réglages IA, ou champ « modèle » de l'étape).")
    if not conf["base_url"].lower().startswith(("http://", "https://")):
        raise AIError("L'URL de l'IA doit commencer par http:// ou https://.")

    content: Any = prompt
    if image:
        data_url = f"data:{image_mime};base64,{base64.b64encode(image).decode('ascii')}"
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": data_url}}]
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
    body = json.dumps(
        {"model": conf["model"], "messages": messages, "temperature": 0, "max_tokens": int(max_tokens), "stream": False}
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "PhysicalShortCut"}
    if conf["key"]:
        headers["Authorization"] = f"Bearer {conf['key']}"
    request = urllib.request.Request(f"{conf['base_url']}/chat/completions", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (http/https verifie)
            raw = response.read(MAX_RESPONSE_BYTES)
        payload = json.loads(raw)
        return str(payload["choices"][0]["message"]["content"]).strip()
    except urllib.error.HTTPError as exc:
        raise AIError(f"L'IA a répondu HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AIError(f"IA injoignable ({conf['base_url']}) : {exc}") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise AIError("Réponse de l'IA illisible.") from None


def classify_drawing(png: bytes, labels: list[str]) -> str | None:
    """Demande a l'IA vision ce qui est dessine ; renvoie un des ``labels`` ou ``None``."""
    choices = ", ".join(labels)
    prompt = (
        "L'image montre un dessin tracé à la main (trait noir sur fond blanc). "
        f"Réponds uniquement par l'un de ces mots : {choices}. "
        "Si rien ne correspond, réponds : aucun."
    )
    answer = ask(prompt, image=png, image_mime="image/png", max_tokens=12).lower()
    for label in sorted(labels, key=len, reverse=True):
        if label.lower() in answer:
            return label
    return None
