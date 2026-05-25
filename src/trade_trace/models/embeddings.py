"""Opt-in local ONNX embeddings for Trade Trace.

This module is deliberately offline-only. It never downloads model assets and
imports optional runtime dependencies lazily so base installs and journal
startup remain unaffected when the embeddings extra is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

LOCAL_EMBEDDINGS_DIM = 384


class LocalEmbeddingUnavailable(RuntimeError):
    """Raised when the local embedding runtime or assets are unavailable."""


def _mean_pool(last_hidden_state: Any, attention_mask: list[int]) -> list[float]:
    values = last_hidden_state.tolist() if hasattr(last_hidden_state, "tolist") else last_hidden_state
    # ORT returns [batch, tokens, hidden]. Only a single query/document is fed.
    token_vectors = values[0] if values and isinstance(values[0], list) else values
    dim = len(token_vectors[0]) if token_vectors else 0
    pooled = [0.0] * dim
    count = 0
    for token_vec, mask in zip(token_vectors, attention_mask, strict=False):
        if int(mask) == 0:
            continue
        count += 1
        for i, value in enumerate(token_vec):
            pooled[i] += float(value)
    if count:
        pooled = [value / count for value in pooled]
    norm = sum(value * value for value in pooled) ** 0.5
    return [value / norm for value in pooled] if norm else pooled


class LocalOnnxEmbedder:
    """Small, dependency-lazy ONNX/tokenizers embedding wrapper."""

    def __init__(self, model_dir: Path) -> None:
        model_path = model_dir / "model.onnx"
        tokenizer_path = model_dir / "tokenizer.json"
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise LocalEmbeddingUnavailable("local ONNX model/tokenizer assets are missing")
        try:
            import onnxruntime as ort  # type: ignore[import-not-found]
            from tokenizers import Tokenizer  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional extra
            raise LocalEmbeddingUnavailable("install trade-trace[embeddings] to use local embeddings") from exc
        try:
            self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
            self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        except Exception as exc:  # pragma: no cover - depends on model/runtime
            raise LocalEmbeddingUnavailable("failed to load local ONNX embedder") from exc

    def embed(self, text: str) -> list[float]:
        try:
            import numpy as np  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - transitive of onnxruntime
            raise LocalEmbeddingUnavailable("numpy is required by local ONNX embeddings") from exc
        encoded = self._tokenizer.encode(text or "")
        input_ids = encoded.ids[:512] or [0]
        attention = [1] * len(input_ids)
        token_type_ids = [0] * len(input_ids)
        ort_inputs: dict[str, Any] = {}
        input_names = {item.name for item in self._session.get_inputs()}
        if "input_ids" in input_names:
            ort_inputs["input_ids"] = np.array([input_ids], dtype=np.int64)
        if "attention_mask" in input_names:
            ort_inputs["attention_mask"] = np.array([attention], dtype=np.int64)
        if "token_type_ids" in input_names:
            ort_inputs["token_type_ids"] = np.array([token_type_ids], dtype=np.int64)
        outputs = self._session.run(None, ort_inputs)
        if not outputs:
            raise LocalEmbeddingUnavailable("local ONNX model returned no outputs")
        vector = _mean_pool(outputs[0], attention)
        if not vector:
            raise LocalEmbeddingUnavailable("local ONNX model returned an empty vector")
        return vector
