"""Project-wide constants, types, and GraphQL metadata loader."""

from __future__ import annotations

import json
import os
import random
import secrets
from pathlib import Path
from typing import Any, Literal

# ──────────────────────────── GraphQL metadata ────────────────────────────

_META_PATH = Path(__file__).parent.parent / "_gql_meta.json"
GQL_META: dict[str, dict[str, Any]] = (
    json.loads(_META_PATH.read_text()) if _META_PATH.exists() else {}
)

# ──────────────────────────── Bearer & URLs ────────────────────────────

# Public web bearer (sama untuk semua user — extracted dari bundle x.com)
WEB_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

HOMEPAGE_URL = "https://x.com/home"
VIEWER_URL = "https://x.com/i/api/graphql/_8ClT24oZ8tpylf_OSuNdg/Viewer"
SEARCH_URL = "https://x.com/i/api/graphql/Yw6L66Pw54NHKuq4Dp7b4Q/SearchTimeline"
GRAPHQL_BASE = "https://x.com/i/api/graphql"
REST_BASE = "https://x.com/i/api/1.1"
DM_BASE = REST_BASE  # alias
UPLOAD_BASE = "https://upload.x.com/i/media/upload.json"
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB

# ──────────────────────────── Browser Fingerprint Profiles (Anti-Detect) ────────────────────────────
# Setiap profil menyelaraskan:
#   1. curl_cffi TLS JA3/JA4 + HTTP/2 AKAMAI fingerprint (`impersonate`)
#   2. `User-Agent` (versi Chrome & OS persis sama dengan profil TLS)
#   3. Client Hints (`sec-ch-ua`, `sec-ch-ua-platform`, `sec-ch-ua-mobile`)
# Dipilih secara DETERMINISTIK per `auth_token` agar 1 akun selalu konsisten
# memakai perangkat/browser yang sama (mencegah deteksi session hijack / bot).

BROWSER_PROFILES: tuple[dict[str, str], ...] = (
    {
        "impersonate": "chrome131",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec_ch_ua_platform": '"Windows"',
    },
    {
        "impersonate": "chrome131",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec_ch_ua_platform": '"macOS"',
    },
    {
        "impersonate": "chrome136",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "sec_ch_ua_platform": '"Windows"',
    },
    {
        "impersonate": "chrome136",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "sec_ch_ua_platform": '"macOS"',
    },
    {
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec_ch_ua_platform": '"Windows"',
    },
    {
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec_ch_ua_platform": '"macOS"',
    },
)

USER_AGENT_POOL: tuple[str, ...] = tuple(p["user_agent"] for p in BROWSER_PROFILES)


def profile_for_token(auth_token: str | None = None) -> dict[str, str]:
    """Pilih profil browser deterministik berdasarkan `auth_token`."""
    if not auth_token:
        return BROWSER_PROFILES[0]
    import hashlib
    idx = int(hashlib.sha256(f"fp:{auth_token}".encode()).hexdigest(), 16) % len(BROWSER_PROFILES)
    return BROWSER_PROFILES[idx]


def headers_for_token(auth_token: str | None = None) -> dict[str, str]:
    """Bangun default HTTP headers yang sinkron dengan profil TLS & UA milik `auth_token`."""
    prof = profile_for_token(auth_token)
    return {
        **DEFAULT_HEADERS,
        "user-agent": prof["user_agent"],
        "sec-ch-ua": prof["sec_ch_ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": prof["sec_ch_ua_platform"],
    }


def random_user_agent() -> str:
    """Random pick UA dari pool (fallback jika tidak ada auth_token)."""
    return random.choice(USER_AGENT_POOL)


def gen_ct0() -> str:
    """Generate 32-char (16 bytes) hex ct0 — sesuai panjang cookie ct0 asli X web."""
    return secrets.token_hex(16)


# ──────────────────────────── Default headers ────────────────────────────

# Header dasar X web client (Fetch API + CORS preflight).
DEFAULT_HEADERS: dict[str, str] = {
    "user-agent": BROWSER_PROFILES[0]["user_agent"],
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://x.com",
    "referer": "https://x.com/home",
    "x-twitter-active-user": "yes",
    "x-twitter-auth-type": "OAuth2Session",
    "x-twitter-client-language": "en",
    "sec-ch-ua": BROWSER_PROFILES[0]["sec_ch_ua"],
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": BROWSER_PROFILES[0]["sec_ch_ua_platform"],
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}

# ──────────────────────────── Viewer / Search features ────────────────────────────

VIEWER_FEATURES: dict[str, bool] = {
    "rweb_xchat_enabled": False,
    "payments_enabled": False,
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}
VIEWER_FIELD_TOGGLES: dict[str, bool] = {"isDelegate": False, "withAuxiliaryUserLabels": False}

SEARCH_FEATURES: dict[str, bool] = {
    "rweb_video_screen_enabled": False,
    "rweb_cashtags_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "rweb_cashtags_composer_attachment_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "rweb_conversational_replies_downvote_enabled": False,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "content_disclosure_indicator_enabled": False,
    "content_disclosure_ai_generated_indicator_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}
SEARCH_FIELD_TOGGLES: dict[str, bool] = {
    "withPayments": False,
    "withAuxiliaryUserLabels": False,
    "withArticleRichContentState": True,
    "withArticlePlainText": False,
    "withArticleSummaryText": False,
    "withArticleVoiceOver": False,
    "withGrokAnalyze": False,
    "withDisallowedReplyControls": False,
}

# ──────────────────────────── DM defaults ────────────────────────────

DM_DEFAULT_PARAMS: dict[str, str] = {
    "include_profile_interstitial_type": "1",
    "include_blocking": "1",
    "include_blocked_by": "1",
    "include_followed_by": "1",
    "include_want_retweets": "1",
    "include_mute_edge": "1",
    "include_can_dm": "1",
    "include_can_media_tag": "1",
    "include_ext_is_blue_verified": "1",
    "include_ext_verified_type": "1",
    "include_ext_profile_image_shape": "1",
    "skip_status": "1",
    "dm_secret_conversations_enabled": "false",
    "krs_registration_enabled": "true",
    "cards_platform": "Web-12",
    "include_cards": "1",
    "include_ext_alt_text": "true",
    "include_ext_limited_action_results": "true",
    "include_quote_count": "true",
    "include_reply_count": "1",
    "tweet_mode": "extended",
    "include_ext_views": "true",
    "dm_users": "true",
    "include_groups": "true",
    "include_inbox_timelines": "true",
    "include_ext_media_color": "true",
    "supports_reactions": "true",
    "include_ext_edit_control": "true",
}

# ──────────────────────────── Stub reasons ────────────────────────────

OAUTH2_USER_CTX_REASON = (
    "Endpoint ini membutuhkan OAuth2 user-context dengan scope khusus "
    "(mis. dm.read, dm.write, tweet.moderate.write). Cookie-auth web mode "
    "tidak menyediakan mekanisme scope yang setara."
)
NEW_GQL_REASON = (
    "Endpoint ini membutuhkan operation GraphQL X yang belum di-discover. "
    "Tambahkan queryId + features ke _gql_meta.json (scrape dari bundle x.com)."
)

# ──────────────────────────── Type aliases ────────────────────────────

SearchType = Literal["Latest", "Top", "People", "Media"]


# ──────────────────────────── Runtime config (env vars) ────────────────────────────

import re as _re

# auth_token format: 40 hex chars (X cookie format).
AUTH_TOKEN_PATTERN = _re.compile(r"^[a-f0-9]{40}$")

# Admin token: required header `X-Admin-Token` untuk akses /cache/stats, /tid/stats.
# Generate dengan `openssl rand -hex 32`. Kosong = endpoint disabled.
ADMIN_TOKEN: str = os.environ.get("ADMIN_TOKEN", "").strip()

# XChat bridge: auto-start bridge untuk bot account di startup.
# Ambil dari env var atau terserah.
XCHAT_BOT_USER_ID: str = os.environ.get("XCHAT_BOT_USER_ID", "").strip()

# Proxy rotation: comma-separated `http://[user:pass@]host:port` urls.
# Random per make_client call. Kosong = no proxy (direct).
_proxy_raw = os.environ.get("PROXY_LIST", "").strip()
PROXY_LIST: tuple[str, ...] = tuple(
    p.strip() for p in _proxy_raw.split(",") if p.strip()
) if _proxy_raw else tuple()


def proxy_for_token(auth_token: str) -> str | None:
    """Proxy deterministik per token — akun yang sama selalu lewat IP sama.

    Pairing stabil bahkan setelah restart (hash token -> index PROXY_LIST).
    """
    if not PROXY_LIST:
        return None
    import hashlib
    idx = int(hashlib.sha256(auth_token.encode()).hexdigest(), 16) % len(PROXY_LIST)
    return PROXY_LIST[idx]


def random_proxy() -> str | None:
    """Random pick proxy dari PROXY_LIST (None kalau kosong)."""
    if not PROXY_LIST:
        return None
    return random.choice(PROXY_LIST)


# Upload media (upload.x.com) direct tanpa proxy — hemat kuota proxy
# (video bisa puluhan MB). 0 = upload ikut jalur proxy.
MEDIA_PROXY_EXEMPT: bool = os.environ.get("MEDIA_PROXY_EXEMPT", "1").strip() not in ("0", "false", "no")

# Disable `?raw=1` di prod (env ENABLE_RAW=0). Default 1 (enabled).
ENABLE_RAW: bool = os.environ.get("ENABLE_RAW", "1").strip() not in ("0", "false", "no")

# Disable `?auth_token=` query auth (env ALLOW_QUERY_AUTH=0). Default 1 (allowed for dev).
# Strongly recommend 0 di production — query string ke-log di reverse proxy.
ALLOW_QUERY_AUTH: bool = os.environ.get("ALLOW_QUERY_AUTH", "1").strip() not in ("0", "false", "no")

# Max body size dalam bytes (default 1 MB).
MAX_BODY_SIZE: int = int(os.environ.get("MAX_BODY_SIZE", str(1 * 1024 * 1024)))

# Allowed CORS origins, comma-separated. Kosong = none allowed.
_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS: tuple[str, ...] = tuple(
    o.strip() for o in _origins_raw.split(",") if o.strip()
) if _origins_raw else tuple()

# Response cache TTL untuk read-only endpoint (detik). 0 = disabled.
RESPONSE_CACHE_TTL: int = int(os.environ.get("RESPONSE_CACHE_TTL", "30"))

# Retry config untuk upstream X calls.
RETRY_MAX_ATTEMPTS: int = int(os.environ.get("RETRY_MAX_ATTEMPTS", "3"))
RETRY_BASE_DELAY: float = float(os.environ.get("RETRY_BASE_DELAY", "0.5"))
RETRY_MAX_DELAY: float = float(os.environ.get("RETRY_MAX_DELAY", "8.0"))

# HTTP client pool size (max simultaneous AsyncSession).
CLIENT_POOL_MAX: int = int(os.environ.get("CLIENT_POOL_MAX", "50"))
CLIENT_POOL_TTL: int = int(os.environ.get("CLIENT_POOL_TTL", "600"))  # 10 min

# ──────────────────────────── Token hashing ────────────────────────────

import hashlib as _hashlib
import secrets as _secrets

# Per-process salt — rotated every restart. Within a single process,
# hashed token values cannot be correlated with other processes.
# NOTE: when using uvicorn --workers > 1, workers inherit the parent's
# salt via fork(), so cross-worker correlation IS possible. For true
# per-worker isolation, spawn workers (--workers N with gunicorn
# --preload off) or use separate container instances.
_TOKEN_SALT: str = _secrets.token_hex(16)


def token_key(auth_token: str) -> str:
    """Return a stable per-process sha256 hash of `auth_token`.

    Used as the cache key in SessionStore, ResponseCache, and ClientPool
    instead of plaintext auth_token. The per-process salt means an attacker
    who captures a memory dump of one process cannot map hashes back to
    original tokens without capturing the salt from that same process
    (which lives alongside the hashes in memory anyway — but prevents
    offline dictionary attacks and cross-process correlation).

    This is NOT a hard cryptographic guarantee (the salt lives in the same
    process) — it's a reasonable defense-in-depth layer against casual
    memory inspection.
    """
    return _hashlib.sha256(f"{_TOKEN_SALT}:{auth_token}".encode()).hexdigest()
