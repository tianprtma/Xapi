"""R106 — gambar E2EE dipanen dari DOM chat yang sudah terdekripsi.

Kasus nyata (conv 1776226317719257088 "cerim bondol"): gambar E2EE tidak
pernah terunduh ke OPFS (unduhan dipicu komponen chat, browser headless
gagal me-render). Tapi client X TETAP mendekripsi & me-render gambar sebagai
`<img src="blob:...">` di shadow DOM — canvas bisa memanen bytes-nya tanpa
RE kripto.

Kontrak (R106):
- `_media_text_hint`: hint pencocokan gambar↔menfess — lowercase, buang token
  trigger (/send, wots) di depan/belakang, ambil maks 5 kata pertama.
- Hint kosong bila teks hanya trigger.
"""
import pytest

from app.xchat_e2ee import _media_text_hint


def test_hint_strips_trigger_words():
    assert _media_text_hint("cerim bondol+ponian, kabarin kalo biru wots") == \
        "cerim bondol+ponian, kabarin kalo biru"


def test_hint_handles_send_prefix():
    assert _media_text_hint("/send halo dunia menfess") == "halo dunia menfess"


def test_hint_case_insensitive():
    assert _media_text_hint("Cerim Bondol+Ponian WOTS") == "cerim bondol+ponian"


def test_hint_only_trigger_returns_empty():
    assert _media_text_hint("wots") == ""
    assert _media_text_hint("/send wots") == ""
    assert _media_text_hint("") == ""


def test_hint_caps_at_five_words():
    assert _media_text_hint("satu dua tiga empat lima enam tujuh") == \
        "satu dua tiga empat lima"