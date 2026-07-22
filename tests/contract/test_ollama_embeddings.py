"""Contract test for the Ollama embeddings client wrapper (tasks.md T029,
contracts/external-integrations.md § Embeddings).

Verifies request shape (`model`, `input`), response parsing into vectors,
and the fail-fast-with-a-clear-local-setup-error behavior when Ollama is
unreachable or returns something unusable — all against a mocked
`requests.Session`, never a live Ollama server.
"""

from unittest.mock import MagicMock

import pytest
import requests

from src.pipeline.embeddings import EMBED_MODEL, OllamaUnavailableError, get_embeddings


def _response(status_code=200, json_body=None, text_body=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_body or {}
    resp.text = text_body
    return resp


def test_request_shape_sends_model_and_input():
    session = MagicMock()
    session.post.return_value = _response(200, {"embeddings": [[0.1, 0.2]]})

    get_embeddings(["hello"], session=session)

    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args[0] == "http://localhost:11434/api/embed"
    assert kwargs["json"] == {"model": EMBED_MODEL, "input": ["hello"]}


def test_successful_response_returns_vectors_in_order():
    session = MagicMock()
    session.post.return_value = _response(200, {"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    vectors = get_embeddings(["a", "b"], session=session)

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_empty_input_returns_empty_without_calling_ollama():
    session = MagicMock()

    vectors = get_embeddings([], session=session)

    assert vectors == []
    session.post.assert_not_called()


def test_unreachable_server_raises_clear_local_setup_error():
    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("refused")

    with pytest.raises(OllamaUnavailableError, match="ollama serve"):
        get_embeddings(["hello"], session=session)


def test_non_2xx_response_raises_ollama_unavailable_error():
    session = MagicMock()
    session.post.return_value = _response(500, text_body="internal error")

    with pytest.raises(OllamaUnavailableError):
        get_embeddings(["hello"], session=session)


def test_mismatched_response_shape_raises_ollama_unavailable_error():
    session = MagicMock()
    # Two inputs requested, only one embedding returned — malformed response.
    session.post.return_value = _response(200, {"embeddings": [[0.1, 0.2]]})

    with pytest.raises(OllamaUnavailableError):
        get_embeddings(["a", "b"], session=session)


def test_missing_embeddings_key_raises_ollama_unavailable_error():
    session = MagicMock()
    session.post.return_value = _response(200, {"unexpected": "shape"})

    with pytest.raises(OllamaUnavailableError):
        get_embeddings(["hello"], session=session)
