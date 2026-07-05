from __future__ import annotations

import json

from app.responses import batch_finalize, write_finalize


def response_json(response):
    return json.loads(response.body.decode())


def test_write_finalize_maps_upstream_errors_to_non_200():
    response = write_finalize(
        {
            "status": "ok",
            "data": {
                "data": {},
                "errors": [
                    {
                        "code": 170,
                        "kind": "Permissions",
                        "name": "AuthorizationError",
                        "message": "not authorized",
                    }
                ],
            },
        },
        raw=False,
    )

    body = response_json(response)

    assert response.status_code == 403
    assert body["errors"][0]["code"] == "UPSTREAM_ERROR"
    assert body["errors"][0]["status"] == 403
    assert "not authorized" in body["errors"][0]["detail"]


def test_write_finalize_keeps_success_payload_200():
    response = write_finalize(
        {
            "status": "ok",
            "data": {"data": {"create_tweet": {"tweet_results": {"id": "1"}}}},
        },
        raw=False,
    )

    body = response_json(response)

    assert response.status_code == 200
    assert body["data"]["data"]["create_tweet"]["tweet_results"]["id"] == "1"


def test_write_finalize_raw_mode_passthrough():
    result = {
        "status": "ok",
        "data": {"errors": [{"message": "upstream failed"}]},
    }

    response = write_finalize(result, raw=True)

    assert response.status_code == 200
    assert response_json(response) == result


def test_write_finalize_supports_formatted_201_success():
    response = write_finalize(
        {"status": "ok", "data": {"note": {"id": "1"}}},
        raw=False,
        formatter=lambda payload: {"formatted": payload["note"]["id"]},
        success_status=201,
    )

    assert response.status_code == 201
    assert response_json(response) == {"formatted": "1"}


def test_batch_finalize_keeps_partial_success_200():
    response = batch_finalize(
        {
            "data": [{"id": "1"}],
            "meta": {"result_count": 1},
            "errors": [{"id": "2", "title": "Not Found"}],
        }
    )

    assert response.status_code == 200


def test_batch_finalize_maps_all_failed_to_404():
    response = batch_finalize(
        {
            "data": [],
            "meta": {"result_count": 0},
            "errors": [{"id": "2", "title": "Not Found"}],
        }
    )

    assert response.status_code == 404
    assert response_json(response)["meta"]["result_count"] == 0


def test_batch_finalize_keeps_empty_success_200():
    response = batch_finalize({"data": [], "meta": {"result_count": 0}})

    assert response.status_code == 200
