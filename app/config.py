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
GQL_META: dict[str, dict[str, Any]] = json.loads(_META_PATH.read_text())

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

# ──────────────────────────── User-Agent pool ────────────────────────────
# Mix Chrome desktop versi 124-132 di Mac/Windows/Linux. Random per request
# supaya traffic tidak terlihat 1-UA-only (red flag anti-bot).

USER_AGENT_POOL: tuple[str, ...] = (
    # Mac (M1+)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)


def random_user_agent() -> str:
    """Random pick UA dari pool (anti-detect: avoid 1-UA-only fingerprint)."""
    return random.choice(USER_AGENT_POOL)


def gen_ct0() -> str:
    """Generate placeholder ct0 (server akan override saat warmup)."""
    return secrets.token_hex(80)


# ──────────────────────────── Default headers ────────────────────────────

# UA di-override per-request (lihat make_client). Header lain konstan.
DEFAULT_HEADERS: dict[str, str] = {
    "user-agent": USER_AGENT_POOL[0],  # default fallback
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://x.com",
    "referer": "https://x.com/",
    "x-twitter-active-user": "yes",
    "x-twitter-auth-type": "OAuth2Session",
    "x-twitter-client-language": "en",
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

# Proxy rotation: comma-separated `http://[user:pass@]host:port` urls.
# Random per make_client call. Kosong = no proxy (direct).
_proxy_raw = os.environ.get("PROXY_LIST", "").strip()
PROXY_LIST: tuple[str, ...] = tuple(
    p.strip() for p in _proxy_raw.split(",") if p.strip()
) if _proxy_raw else tuple()


def random_proxy() -> str | None:
    """Random pick proxy dari PROXY_LIST (None kalau kosong)."""
    if not PROXY_LIST:
        return None
    return random.choice(PROXY_LIST)


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
