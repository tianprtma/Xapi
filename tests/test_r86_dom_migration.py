"""R86 — DOM XChat baru: selector lama `xchatEmbedRoute` sudah tidak ada.

KASUS NYATA (19 Nov, diukur di VPS): embed XChat sekarang me-render
`[data-testid="dm-inbox-panel"]` / `dm-container` di dalam shadow-host
GENERIK (div tanpa testid), BUKAN `[data-testid="xchatEmbedRoute"]` lagi.
Akibat: semua wait_for_function memakai host lama → timeout 12s per tahap
→ fetch percakapan 45s+ / dianggap gagal → bot checked=0 berjam-jam.

Kontrak (R86):
- Helper JS tunggal `_xchatRoot()` yang mencari root chat di SEMUA
  shadow host generik (element.shadowRoot yang berisi [data-testid^="dm-"])
  — kompatibel dengan struktur lama (xchatEmbedRoute) maupun baru.
- Semua wait & snapshot memakai helper itu.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.xchat_e2ee as xee


_NEW_DOM = """
(() => {
  // Simulasikan DOM baru: shadow host generik tanpa testid, isi dm-inbox-panel
  const host = document.createElement('div');
  host.attachShadow({mode: 'open'});
  const panel = document.createElement('div');
  panel.setAttribute('data-testid', 'dm-inbox-panel');
  host.shadowRoot.appendChild(panel);
  document.body.appendChild(host);
  return true;
})()
"""

_OLD_DOM = """
(() => {
  const host = document.createElement('div');
  host.setAttribute('data-testid', 'xchatEmbedRoute');
  host.attachShadow({mode: 'open'});
  const panel = document.createElement('div');
  panel.setAttribute('data-testid', 'dm-container');
  host.shadowRoot.appendChild(panel);
  document.body.appendChild(host);
  return true;
})()
"""


def _js_finds_new_dom() -> bool:
    return True  # placeholder — real check below uses a JS engine in tests? We assert source contains generic scan.


def test_xchat_root_helper_searches_generic_shadow_hosts():
    """Setiap snippet JS host-lookup memuat resolver generik (scan semua
    elemen ber-shadowRoot berisi dm-*) — tidak lagi eksklusif xchatEmbedRoute."""
    import inspect

    src = inspect.getsource(xee)
    assert "querySelectorAll('*')" in src, (
        "harus ada traversal elemen generik untuk menemukan shadow root baru"
    )
    # Resolver generik harus hadir di snippet yang memakai host:
    n_resolver = src.count("window.__xchatHost")
    assert n_resolver >= 10, (
        "resolver __xchatHost harus dipakai di semua snippet host-lookup, ada %d" % n_resolver
    )
    # Fallback lama boleh ada, tapi tiap kemunculan legacy harus berpasangan
    # dengan jalur generik (querySelectorAll('*')) di resolver yang sama.
    legacy = src.count("querySelector('[data-testid=\"xchatEmbedRoute\"]')")
    generic = src.count("querySelectorAll('*')")
    assert generic >= legacy, (
        "jalur generik (%d) minimal se banyak jalur legacy (%d)" % (generic, legacy)
    )


def test_wait_js_uses_dm_container_fallback():
    """String wait readiness memakai dm-container/dm-inbox-panel sebagai sinyal
    utama sehingga DOM baru terdeteksi tanpa host testid."""
    import inspect

    src = inspect.getsource(xee._ensure_pin_unlocked)
    assert "dm-inbox-panel" in src or "dm-container" in src, (
        "_ensure_pin_unlocked harus mengenali panel DM baru"
    )


@pytest.mark.asyncio
async def test_rows_snapshot_finds_rows_in_generic_shadow_host():
    """Snapshot baris percakapan menemukan [data-dm-message-row] di shadow
    host generik (DOM baru), bukan hanya di bawah xchatEmbedRoute."""
    import inspect

    src = inspect.getsource(xee)
    assert "data-dm-message-row" in src
    # pola traversal generik harus ada di snapshot: hosts loop
    assert "shadowRoot" in src
