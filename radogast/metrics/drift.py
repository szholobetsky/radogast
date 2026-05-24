"""Embedding-based drift angle between origin vector and current context window."""
from __future__ import annotations
import numpy as np

_model_cache: dict[str, object] = {}


def _get_model(model_name: str):
    if model_name not in _model_cache:
        try:
            import sys
            print(f"  [radogast] loading model {model_name}...", file=sys.stderr, flush=True)
            from sentence_transformers import SentenceTransformer
            _model_cache[model_name] = SentenceTransformer(model_name)
            print(f"  [radogast] model ready.", file=sys.stderr, flush=True)
        except ImportError:
            return None
    return _model_cache[model_name]


def embed(texts: list[str], model_name: str) -> np.ndarray | None:
    model = _get_model(model_name)
    if model is None:
        return None
    return model.encode(texts, normalize_embeddings=True)


def cosine_angle(v1: np.ndarray, v2: np.ndarray) -> float:
    cos = float(np.dot(v1, v2))  # pre-normalized → dot = cosine
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def compute_drift(
    messages: list[str],
    goal: str,
    key_terms: list[str],
    model_name: str,
    max_window: int = 5,
) -> dict:
    """
    Returns drift_angle (degrees) and status, or None values if embeddings unavailable.
    """
    origin_text = goal + " " + " ".join(key_terms)
    current_text = " ".join(messages[-max_window:])

    vecs = embed([origin_text, current_text], model_name)
    if vecs is None:
        return {"angle": None, "status": "no_embeddings", "available": False}

    angle = cosine_angle(vecs[0], vecs[1])
    if angle <= 40.0:
        status = "on_track"
    elif angle <= 65.0:
        status = "warning"
    else:
        status = "critical"

    return {"angle": round(angle, 1), "status": status, "available": True}


def compute_trajectory(
    messages: list[str],
    goal: str,
    key_terms: list[str],
    model_name: str,
) -> list[float] | None:
    """Drift angle at each message turn (for timeline visualization)."""
    origin_text = goal + " " + " ".join(key_terms)
    texts = [origin_text] + [" ".join(messages[: i + 1]) for i in range(len(messages))]
    vecs = embed(texts, model_name)
    if vecs is None:
        return None
    origin_vec = vecs[0]
    return [round(cosine_angle(origin_vec, vecs[i + 1]), 1) for i in range(len(messages))]
