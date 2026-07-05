# Error Code Reference

Setiap error response memiliki `code` machine-readable di field `errors[].code`.
Gunakan code ini untuk branching di client — jangan parse string `detail`.

## AUTH_* — Authentication

| Code | HTTP | Template |
|------|------|---------|
| `AUTH_TOKEN_MISSING` | 401 | missing auth_token (provide Authorization header) |
| `AUTH_TOKEN_INVALID_FORMAT` | 401 | auth_token must be 40 hex characters |
| `AUTH_TOKEN_EXPIRED` | 401 | auth_token expired or invalid |
| `AUTH_QUERY_DISABLED` | 401 | query-string auth disabled |
| `AUTH_ADMIN_REQUIRED` | 401 | valid X-Admin-Token header required |

## UPSTREAM_* — X Upstream

| Code | HTTP | Template |
|------|------|---------|
| `UPSTREAM_ERROR` | 502 | X upstream returned {http_status} |
| `UPSTREAM_TIMEOUT` | 504 | X upstream timed out |
| `UPSTREAM_NON_JSON` | 502 | X returned non-JSON response |
| `UPSTREAM_RETRY_EXHAUSTED` | 502 | X upstream still failing after {attempts} attempts |
| `UPSTREAM_AUTH_REJECTED` | 401 | X rejected this session |

## VALIDATION_* — Input

| Code | HTTP | Template |
|------|------|---------|
| `VALIDATION_BODY_SIZE` | 413 | request body exceeds {max_bytes} bytes |
| `VALIDATION_MISSING_PARAM` | 400 | required parameter '{param}' is missing |
| `VALIDATION_INVALID_PARAM` | 400 | parameter '{param}' is invalid |
| `VALIDATION_MEDIA_SIZE` | 413 | media upload exceeds {max_bytes} bytes |

## RATE_* — Rate Limiting

| Code | HTTP | Template |
|------|------|---------|
| `RATE_LIMIT_EXCEEDED` | 429 | rate limit exceeded — retry after {retry_after}s |

## INFRA_* — Internal

| Code | HTTP | Template |
|------|------|---------|
| `INFRA_UNKNOWN_OPERATION` | 500 | unknown GraphQL operation |
| `INFRA_INTERNAL_ERROR` | 500 | internal server error |
| `INFRA_SERVICE_UNAVAILABLE` | 503 | service temporarily unavailable |
| `INFRA_NOT_FOUND` | 404 | no API route matches {method} {path} |
| `INFRA_RAW_DISABLED` | 403 | raw mode disabled |

## MEDIA_* — Upload

| Code | HTTP | Template |
|------|------|---------|
| `MEDIA_INIT_FAILED` | 502 | media INIT failed |
| `MEDIA_APPEND_FAILED` | 502 | media APPEND segment {segment} failed |
| `MEDIA_FINALIZE_FAILED` | 502 | media FINALIZE failed |
| `MEDIA_PROCESSING_FAILED` | 502 | media processing failed |

## XCHAT_* — XChat Bridge

| Code | HTTP | Template |
|------|------|---------|
| `XCHAT_BRIDGE_UNAVAILABLE` | 503 | XChat bridge not ready |
| `XCHAT_BRIDGE_AUTH_REJECTED` | 401 | XChat bridge auth_token invalid |
| `XCHAT_BRIDGE_MAX_REBUILDS` | 503 | XChat bridge exceeded max rebuilds |

## STUB_* — Unimplemented

| Code | HTTP | Template |
|------|------|---------|
| `STUB_NOT_IMPLEMENTED` | 501 | {reason} |
| `STUB_OAUTH2_REQUIRED` | 501 | endpoint requires OAuth2 user-context |
| `STUB_NEW_GQL_REQUIRED` | 501 | undiscovered GraphQL operation |
