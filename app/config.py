"""Project-wide constants, types, and GraphQL metadata loader."""

from __future__ import annotations

import contextvars
import hashlib
import ipaddress
import json
import os
import random
import secrets
import socket
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import unquote, urlparse

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

# Izinkan klien mengirim header `X-Proxy-Url` per-request agar tiap project
# (menfessllm, jkt48history, dll.) mengatur proxy sendiri di `.env` masing-masing.
# 0 = tolak header `X-Proxy-Url` (rekomendasi jika Xapi diekspos ke publik).
ALLOW_REQUEST_PROXY: bool = os.environ.get("ALLOW_REQUEST_PROXY", "1").strip().lower() not in ("0", "false", "no")

_DIRECT_PROXY_SENTINEL = "__direct__"
_ALLOWED_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})
_REQUEST_PROXY_VAR: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "xapi_request_proxy", default=None
)


_PROXY_CREDS_RE = _re.compile(
    r"((?:https?|socks5h?)://)"
    r"(?:[^\s/?#:'\"<>]+:(?![0-9]{1,5}[/?#])(?:(?!://)\S)*?|[^\s/?#'\"<>]+)@"
    r"(?=(?:\[[0-9a-fA-F:]+\]|[a-zA-Z0-9.-]+)(?::\d{1,5})?(?:[\s/'\"<>),;\]}.!?#]|:(?!\d)|$))",
    _re.IGNORECASE,
)
_PROXY_SHORTHAND_CREDS_RE = _re.compile(
    r"((?<![A-Za-z0-9._/-])(?:\[[0-9a-fA-F:]+\]|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\.?):\d{1,5}):[^\s,'\";\]})]+:[^\s,'\";\]})]+"
)
_PROXY_SCHEMELESS_AT_RE = _re.compile(
    r"(?:(?<=[\s'\"(<\[,;={])|^)[^\s/:'\"<>@=]+:(?!//)(?:(?!://)[^\s'\"<>])+@(?=(?:\[[0-9a-fA-F:]+\]|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.?):\d{1,5}(?:[\s/'\"<>),;\]}.!?#]|:(?!\d)|$))"
)
_DISALLOWED_PROXY_HOSTS = frozenset({
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.goog",
    "metadata.google.internal",
    "metadata.azure.internal",
    "instance-data",
    "instance-data.ec2.internal",
})
_VALID_PROXY_HOST_RE = _re.compile(r"^[a-z0-9.:-]+$")
_HEX_LABEL_RE = _re.compile(r"^0x[0-9a-f]+$")
_PCT_HEX_RE = _re.compile(r"%[0-9A-Fa-f]{2}")
_BAD_PCT_RE = _re.compile(r"%(?![0-9A-Fa-f]{2})")
_VALID_USERINFO_RE = _re.compile(r"^[A-Za-z0-9._~%!$&()*+,:=-]+$")
_SAFE_USERINFO_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def _encode_userinfo_component(raw_part: str) -> str:
    """Encode komponen user/pass sesuai RFC 3986 tanpa meng-encode ulang %XX yang sudah valid."""
    out: list[str] = []
    i = 0
    n = len(raw_part)
    while i < n:
        ch = raw_part[i]
        if ch == "%" and i + 2 < n and _PCT_HEX_RE.match(raw_part, i):
            out.append(raw_part[i : i + 3].upper())
            i += 3
            continue
        if ch in _SAFE_USERINFO_CHARS:
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
        i += 1
    return "".join(out)


def _encode_userinfo(userinfo: str) -> str:
    if ":" in userinfo:
        u, p = userinfo.split(":", 1)
        return f"{_encode_userinfo_component(u)}:{_encode_userinfo_component(p)}"
    return _encode_userinfo_component(userinfo)


def _canon_ipv6_bracket(hb: str) -> str:
    raw_v6 = hb[1:] if hb.startswith("[") else hb
    try:
        return f"[{ipaddress.IPv6Address(raw_v6)}]"
    except ValueError:
        return f"{hb.lower()}]"


def _canon_hostport_text(hostport: str) -> str:
    """Lowercase host, compress IPv6, strip trailing dot, and strip leading zeros on numeric port."""
    if hostport.startswith("["):
        hb, bsep, tail = hostport.partition("]")
        if not bsep:
            return hostport.lower()
        v6_fmt = _canon_ipv6_bracket(hb)
        if tail.startswith(":") and tail[1:].isdigit() and 1 <= int(tail[1:]) <= 65535:
            return f"{v6_fmt}:{int(tail[1:])}"
        return f"{v6_fmt}{tail}"
    h_part, csep, p_part = hostport.rpartition(":")
    if csep and p_part.isdigit() and 1 <= int(p_part) <= 65535:
        h_clean = h_part.lower().rstrip(".") or h_part.lower()
        return f"{h_clean}:{int(p_part)}"
    return hostport.lower().rstrip(".") or hostport.lower()


_MULTI_LABEL_HOST_RE = _re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\.?$")


def _has_valid_port_suffix(hostport: str) -> bool:
    hp = hostport[:-1] if (hostport.endswith("/") and "/" not in hostport[:-1]) else hostport
    if hp.startswith("["):
        hb, bsep, tail = hp.partition("]")
        if not (bsep and tail.startswith(":") and tail[1:].isdigit() and 1 <= int(tail[1:]) <= 65535):
            return False
        try:
            ipaddress.IPv6Address(hb[1:])
            return True
        except ValueError:
            return False
    h_p, csep, p_p = hp.rpartition(":")
    return bool(
        csep
        and h_p
        and _MULTI_LABEL_HOST_RE.match(h_p)
        and p_p.isdigit()
        and 1 <= int(p_p) <= 65535
    )


def normalize_proxy_input(raw: str) -> str:
    """Normalisasi input proxy dari CLI / env (`PROXY_LIST`, `--proxy`):
    dukung URL penuh, `direct`/`none`, `user:pass@host:port`, `[ipv6]:port[:user:pass]`,
    serta shorthand provider `host:port:user:pass` / `host:port`."""
    from urllib.parse import quote as _quote

    val = (raw or "").strip()
    while len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1].strip()
    if not val:
        return ""
    if val.lower() in ("direct", "none"):
        return val.lower()
    sch_cand, has_sch, rest = val.partition("://")
    if has_sch and sch_cand and sch_cand[0].isalpha() and all(c.isalnum() or c in "+.-" for c in sch_cand):
        scheme = sch_cand.lower()
        if "@" in rest:
            userinfo, _, hostport = rest.rpartition("@")
            if hostport.endswith("/") and "/" not in hostport[:-1]:
                hostport = hostport[:-1]
            if userinfo and hostport and "/" not in hostport and "?" not in hostport and "#" not in hostport:
                return f"{scheme}://{_encode_userinfo(userinfo)}@{_canon_hostport_text(hostport)}"
        else:
            if rest.endswith("/") and "/" not in rest[:-1]:
                rest = rest[:-1]
            if "/" not in rest and "?" not in rest and "#" not in rest:
                return f"{scheme}://{_canon_hostport_text(rest)}"
        return f"{scheme}://{rest}"
    if val.startswith("["):
        host_bracket, bsep, tail = val.partition("]")
        if bsep and tail.startswith(":"):
            v6_fmt = _canon_ipv6_bracket(host_bracket)
            rest_parts = tail[1:].split(":", 2)
            p0 = rest_parts[0][:-1] if (len(rest_parts) == 1 and rest_parts[0].endswith("/")) else rest_parts[0]
            if len(rest_parts) == 1 and p0.isdigit() and 1 <= int(p0) <= 65535:
                return f"http://{v6_fmt}:{int(p0)}"
            if len(rest_parts) == 3 and rest_parts[0].isdigit() and 1 <= int(rest_parts[0]) <= 65535:
                port_s, u_s, p_s = rest_parts
                return f"http://{_quote(u_s, safe='')}:{_quote(p_s, safe='')}@{v6_fmt}:{int(port_s)}"
        return val
    parts = val.split(":", 3)
    is_at_hostport = (
        "@" in val
        and "." not in parts[0]
        and _has_valid_port_suffix(val.rpartition("@")[2])
    )
    if (
        not is_at_hostport
        and len(parts) == 4
        and parts[0]
        and all(c not in parts[0] for c in "/@#?")
        and parts[1].isdigit()
        and 1 <= int(parts[1]) <= 65535
    ):
        h_clean = parts[0].lower().rstrip(".") or parts[0].lower()
        return f"http://{_quote(parts[2], safe='')}:{_quote(parts[3], safe='')}@{h_clean}:{int(parts[1])}"
    p2_port = parts[1][:-1] if (len(parts) == 2 and parts[1].endswith("/")) else (parts[1] if len(parts) == 2 else "")
    if (
        len(parts) == 2
        and parts[0]
        and all(c not in parts[0] for c in "/@#?")
        and p2_port.isdigit()
        and 1 <= int(p2_port) <= 65535
    ):
        h_clean = parts[0].lower().rstrip(".") or parts[0].lower()
        return f"http://{h_clean}:{int(p2_port)}"
    if "@" in val:
        userinfo, sep, hostport = val.rpartition("@")
        if hostport.endswith("/") and "/" not in hostport[:-1]:
            hostport = hostport[:-1]
        if sep and userinfo and hostport and "/" not in hostport and "?" not in hostport and "#" not in hostport:
            return f"http://{_encode_userinfo(userinfo)}@{_canon_hostport_text(hostport)}"
    return val


def redact_proxy_creds(text: str) -> str:
    """Mask kredensial (`user:pass@`, `token@`, maupun shorthand `host:port:user:pass`) agar tidak bocor ke log/error."""
    if not text:
        return text
    out = _PROXY_CREDS_RE.sub(r"\1***@", text) if "://" in text else text
    if "@" in out and ":" in out:
        out = _PROXY_SCHEMELESS_AT_RE.sub("***@", out)
    if ":" in out:
        out = _PROXY_SHORTHAND_CREDS_RE.sub(r"\1:***", out)
    return out


_NAT64_WELL_KNOWN = ipaddress.IPv6Network("64:ff9b::/96")
_NAT64_LOCAL_USE = ipaddress.IPv6Network("64:ff9b:1::/48")
_SIIT_IPV4_TRANSLATED = ipaddress.IPv6Network("::ffff:0:0/96")


def _is_disallowed_proxy_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True bila IP (atau IPv4 tertanam di IPv6 mapped/6to4/teredo/NAT64/SIIT) tidak aman untuk proxy."""
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return True
    # RFC 1122 0.0.0.0/8 ("this network") — pada Linux dapat merutekan ke host lokal.
    if isinstance(ip, ipaddress.IPv4Address) and ip.packed[0] == 0:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None and _is_disallowed_proxy_ip(ip.ipv4_mapped):
            return True
        if ip.sixtofour is not None and _is_disallowed_proxy_ip(ip.sixtofour):
            return True
        if ip.teredo is not None:
            for sub in ip.teredo:
                if _is_disallowed_proxy_ip(sub):
                    return True
        if ip in _NAT64_WELL_KNOWN or ip in _NAT64_LOCAL_USE or ip in _SIIT_IPV4_TRANSLATED:
            embedded_v4 = ipaddress.IPv4Address(ip.packed[12:16])
            if _is_disallowed_proxy_ip(embedded_v4):
                return True
    return False


def validate_proxy_url(raw: str) -> str:
    """Validasi & kanonikalisasi URL proxy dari header `X-Proxy-Url` (tolak skema asing / loopback SSRF)."""
    raw_str = raw or ""
    # Cek karakter kontrol (<32 / >=127) & non-ASCII SEBELUM strip agar \r/\n/\x0b/\x0c
    # tidak lolos diam-diam melalui str.strip().
    if any(ord(ch) < 32 or ord(ch) >= 127 or ch == "\\" for ch in raw_str):
        raise ValueError("proxy URL mengandung karakter terlarang")
    val = raw_str.strip(" \t")
    if not val:
        raise ValueError("proxy URL kosong")
    if any(ch in val for ch in (" ", "\t")):
        raise ValueError("proxy URL mengandung karakter terlarang")
    if val.lower() in ("direct", "none"):
        return _DIRECT_PROXY_SENTINEL
    try:
        parsed = urlparse(val)
    except ValueError as exc:
        raise ValueError("format URL proxy tidak valid") from exc
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_PROXY_SCHEMES:
        raise ValueError("skema proxy harus http, https, socks5, atau socks5h")
    if parsed.params or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("URL proxy tidak boleh mengandung path, query, atau fragment")
    host = (parsed.hostname or "").strip().lower()
    host_clean = host.rstrip(".")
    if not host_clean:
        raise ValueError("host proxy tidak valid")
    if "%" in host_clean or not _VALID_PROXY_HOST_RE.match(host_clean):
        raise ValueError("host proxy mengandung karakter/encoding tidak valid")
    if host_clean in _DISALLOWED_PROXY_HOSTS or host_clean.endswith(".localhost"):
        raise ValueError("host proxy loopback/metadata internal tidak diizinkan")
    ip_candidate = host_clean
    parsed_ip = None
    try:
        parsed_ip = ipaddress.ip_address(ip_candidate)
    except ValueError:
        parsed_ip = None
    if parsed_ip is not None:
        if _is_disallowed_proxy_ip(parsed_ip):
            raise ValueError("alamat IP proxy loopback/link-local/reserved tidak diizinkan")
        host_fmt = f"[{parsed_ip}]" if isinstance(parsed_ip, ipaddress.IPv6Address) else str(parsed_ip)
    else:
        labels = host_clean.split(".")
        if len(host_clean) > 253 or any(
            not lbl or len(lbl) > 63 or lbl.startswith("-") or lbl.endswith("-") or ":" in lbl
            for lbl in labels
        ):
            raise ValueError("host proxy tidak valid")
        # RFC 3696 / WHATWG URL Standard: TLD (label terakhir) DNS tidak pernah
        # seluruhnya digit atau literal hex `0x...` — menolak seluruh varian IPv4
        # non-kanonik (integer 32/64-bit, hex, oktal `0177...`, pseudo-oktal `127.0.0.08`, shorthand `127.1`).
        if labels[-1].isdigit() or _HEX_LABEL_RE.match(labels[-1]):
            raise ValueError("format IPv4 non-kanonik atau TLD numerik tidak diizinkan")
        host_fmt = host_clean
    userinfo, sep, hostport = parsed.netloc.rpartition("@")
    if sep:
        if not userinfo or userinfo == ":":
            raise ValueError("kredensial userinfo proxy kosong")
        # Tolak `;` mentah (divergensi urlparse Python <3.12 vs 3.12+), quote, `<>`, `[]`, `@`,
        # serta `%` yang bukan `%XX` valid; seragamkan hex `%XX` menjadi huruf besar.
        if not _VALID_USERINFO_RE.match(userinfo) or _BAD_PCT_RE.search(userinfo):
            raise ValueError("userinfo proxy mengandung karakter/encoding tak valid")
        userinfo = _PCT_HEX_RE.sub(lambda m: m.group(0).upper(), userinfo)
    # Ekstrak raw port secara ketat (hanya digit ASCII, tolak `+8080` atau `:`)
    if hostport.startswith("["):
        if not isinstance(parsed_ip, ipaddress.IPv6Address):
            raise ValueError("kurung siku hanya untuk alamat IPv6")
        _, bracket_sep, port_part = hostport.partition("]")
        if not bracket_sep:
            raise ValueError("host IPv6 proxy tidak valid")
        if port_part and not port_part.startswith(":"):
            raise ValueError("port proxy tidak valid")
        has_colon = port_part.startswith(":")
        raw_port = port_part[1:] if has_colon else ""
    else:
        _, colon_sep, raw_port = hostport.rpartition(":")
        has_colon = bool(colon_sep)
    if has_colon and (not raw_port or not raw_port.isdigit()):
        raise ValueError("port proxy tidak valid")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("port proxy tidak valid") from exc
    if port is not None and not (1 <= port <= 65535):
        raise ValueError("port proxy di luar rentang 1-65535")
    # Kanonikalisasi skema, host/IP, dan integer port (tanpa leading zero / trailing `/`)
    # agar key ClientPool/SessionStore/ContextPool tidak terfragmentasi.
    canon_hostport = f"{host_fmt}:{port}" if port is not None else host_fmt
    canon_netloc = f"{userinfo}@{canon_hostport}" if sep else canon_hostport
    return f"{scheme}://{canon_netloc}"


def _canon_static_proxy(raw: str) -> str:
    """Kanonikalisasi entry PROXY_LIST (dukung shorthand `host:port:user:pass`,
    `user:pass@host:port`, `[ipv6]:port`, lowercase skema/host, tanpa trailing `/`,
    serta tolak entry tidak valid/loopback)."""
    val = normalize_proxy_input(raw)
    if not val or val in ("direct", "none"):
        return ""
    try:
        canon = validate_proxy_url(val)
        return "" if canon == _DIRECT_PROXY_SENTINEL else canon
    except ValueError:
        import logging as _logging
        _logging.getLogger("xapi.config").warning("PROXY_LIST entry diabaikan karena tidak valid")
        return ""


# Proxy rotation: comma-separated `http://[user:pass@]host:port` urls.
# Deterministik per auth_token. Kosong = no proxy (direct).
_proxy_raw = os.environ.get("PROXY_LIST", "").strip()
PROXY_LIST: tuple[str, ...] = tuple(
    c for p in _proxy_raw.split(",") if (c := _canon_static_proxy(p))
) if _proxy_raw else tuple()


def get_request_proxy() -> Optional[str]:
    return _REQUEST_PROXY_VAR.get()


def set_request_proxy(proxy_url: Optional[str]) -> contextvars.Token:
    return _REQUEST_PROXY_VAR.set(proxy_url)


def reset_request_proxy(tok: contextvars.Token) -> None:
    _REQUEST_PROXY_VAR.reset(tok)


def proxy_for_token(auth_token: str) -> str | None:
    """Resolve proxy aktif: override header `X-Proxy-Url` per-request menang,
    lalu fallback ke `PROXY_LIST` deterministik per `auth_token`. None = direct.
    """
    req_proxy = _REQUEST_PROXY_VAR.get()
    if req_proxy == _DIRECT_PROXY_SENTINEL:
        return None
    if req_proxy:
        return req_proxy
    if not PROXY_LIST:
        return None
    idx = int(hashlib.sha256(auth_token.encode()).hexdigest(), 16) % len(PROXY_LIST)
    return PROXY_LIST[idx]


def playwright_proxy_for_token(auth_token: str) -> Optional[dict[str, str]]:
    """Konversi `proxy_for_token(auth_token)` ke dict konfigurasi proxy Playwright."""
    proxy_url = proxy_for_token(auth_token)
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    scheme = (parsed.scheme or "http").lower()
    if scheme == "socks5h":
        scheme = "socks5"
    host = parsed.hostname or ""
    if not host:
        return None
    if ":" in host and not host.startswith("["):
        host_fmt = f"[{host}]"
    else:
        host_fmt = host
    try:
        port = parsed.port
    except ValueError:
        return None
    server = f"{scheme}://{host_fmt}:{port}" if port else f"{scheme}://{host_fmt}"
    cfg: dict[str, str] = {"server": server}
    if parsed.username is not None:
        cfg["username"] = unquote(parsed.username)
    if parsed.password is not None:
        cfg["password"] = unquote(parsed.password)
    return cfg


def random_proxy() -> str | None:
    """Random pick proxy dari PROXY_LIST (None kalau kosong)."""
    if not PROXY_LIST:
        return None
    return random.choice(PROXY_LIST)


# Upload media (upload.x.com) direct tanpa proxy — hemat kuota proxy
# (video bisa puluhan MB). 0 = upload ikut jalur proxy.
MEDIA_PROXY_EXEMPT: bool = os.environ.get("MEDIA_PROXY_EXEMPT", "1").strip().lower() not in ("0", "false", "no")

# Disable `?raw=1` di prod (env ENABLE_RAW=0). Default 1 (enabled).
ENABLE_RAW: bool = os.environ.get("ENABLE_RAW", "1").strip().lower() not in ("0", "false", "no")

# Disable `?auth_token=` query auth (env ALLOW_QUERY_AUTH=0). Default 1 (allowed for dev).
# Strongly recommend 0 di production — query string ke-log di reverse proxy.
ALLOW_QUERY_AUTH: bool = os.environ.get("ALLOW_QUERY_AUTH", "1").strip().lower() not in ("0", "false", "no")

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
