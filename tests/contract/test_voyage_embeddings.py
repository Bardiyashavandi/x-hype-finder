"""Contract test for the Voyage AI embeddings client wrapper
(contracts/external-integrations.md § Embeddings).

Verifies request shape (`model`, `input`, bearer auth header), response
parsing into index-ordered vectors, and the fail-fast-with-a-clear-error
behavior when Voyage AI is unreachable or returns something unusable — all
against a mocked `requests.Session`, never a live Voyage AI call.
"""

from unittest.mock import MagicMock

import pytest
import requests

from src.pipeline.embeddings_voyage import EMBED_MODEL, VoyageUnavailableError, get_embeddings


def _response(status_code=200, json_body=None, text_body=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_body or {}
    resp.text = text_body
    return resp


def test_request_shape_sends_model_input_and_bearer_auth():
    session = MagicMock()
    session.post.return_value = _response(200, {"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    get_embeddings(["hello"], api_key="test-key", session=session)

    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args[0] == "https://api.voyageai.com/v1/embeddings"
    assert kwargs["json"] == {"model": EMBED_MODEL, "input": ["hello"]}
    assert kwargs["headers"] == {"Authorization": "Bearer test-key"}


def test_successful_response_returns_vectors_in_order():
    session = MagicMock()
    session.post.return_value = _response(
        200,
        {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        },
    )

    vectors = get_embeddings(["a", "b"], api_key="test-key", session=session)

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_empty_input_returns_empty_without_calling_voyage():
    session = MagicMock()

    vectors = get_embeddings([], api_key="test-key", session=session)

    assert vectors == []
    session.post.assert_not_called()


def test_unreachable_api_raises_clear_error():
    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("refused")

    with pytest.raises(VoyageUnavailableError, match="VOYAGE_API_KEY"):
        get_embeddings(["hello"], api_key="test-key", session=session)


def test_non_2xx_response_raises_voyage_unavailable_error():
    session = MagicMock()
    session.post.return_value = _response(401, text_body="invalid api key")

    with pytest.raises(VoyageUnavailableError):
        get_embeddings(["hello"], api_key="bad-key", session=session)


def test_mismatched_response_shape_raises_voyage_unavailable_error():
    session = MagicMock()
    # Two inputs requested, only one embedding returned — malformed response.
    session.post.return_value = _response(200, {"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    with pytest.raises(VoyageUnavailableError):
        get_embeddings(["a", "b"], api_key="test-key", session=session)


def test_missing_data_key_raises_voyage_unavailable_error():
    session = MagicMock()
    session.post.return_value = _response(200, {"unexpected": "shape"})

    with pytest.raises(VoyageUnavailableError):
        get_embeddings(["hello"], api_key="test-key", session=session)


def test_malformed_data_items_raise_voyage_unavailable_error():
    session = MagicMock()
    session.post.return_value = _response(200, {"data": [{"embedding": [0.1, 0.2]}]})

    with pytest.raises(VoyageUnavailableError):
        get_embeddings(["hello"], api_key="test-key", session=session)
