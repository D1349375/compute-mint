"""Placeholders written with JSON \\u escapes (found 2026-10-31 with a real client) are restored too."""
import json
import random

from upstream_sim import cuts

from compute_mint.vault import StreamRestorer, Vault

KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
EMAIL = "lin" + "@quill-" + "mail.test"
OPEN, CLOSE = "\\u27e8", "\\u27e9"      # the six characters a JSON writer may use for the two brackets


def _vault():
    vault = Vault()
    vault.mask(f"{KEY} {EMAIL}")
    return vault


def _escaped(text):
    return text.replace("⟨", OPEN).replace("⟩", CLOSE)


def test_rehydrate_json_restores_placeholders_written_with_u_escapes():
    vault = _vault()
    for spelling in (f'{{"k": "{OPEN}API_KEY_1{CLOSE}"}}', f'{{"k": "{OPEN}API_KEY_1{CLOSE.upper().replace("U", "u")}"}}',
                     f'{{"k": "⟨API_KEY_1{CLOSE}"}}', f'{{"k": "{OPEN.replace("e", "E")}API_KEY_1⟩"}}'):
        assert json.loads(vault.rehydrate_json(spelling)) == {"k": KEY}


def test_an_escaped_backslash_before_u27e8_is_not_a_placeholder():
    vault = _vault()
    literal = '{"k": "\\\\u27e8API_KEY_1\\\\u27e9"}'     # JSON for the text ⟨API_KEY_1⟩ with a real backslash
    assert vault.rehydrate_json(literal) == literal
    assert json.loads(vault.rehydrate_json(literal)) == {"k": "\\u27e8API_KEY_1\\u27e9"}


def test_escaped_placeholders_in_streamed_json_for_any_split():
    rng = random.Random(5)
    vault = _vault()
    atoms = ["⟨API_KEY_1⟩", "⟨EMAIL_1⟩", "⟨UNKNOWN_9⟩", "plain ", "\\n", "\\\\", "\\u00e9",
             "日本語", "⟨API_"]
    for _ in range(3000):
        text = _escaped("".join(rng.choice(atoms) for _ in range(rng.randrange(1, 9))))
        restorer = StreamRestorer(vault, json_text=True)
        out = "".join(restorer.feed(piece) for piece in cuts(text, rng, most=9)) + restorer.flush()
        assert out == vault.rehydrate_json(text), text


def test_a_cut_inside_an_escape_is_held_until_it_is_known():
    vault = _vault()
    restorer = StreamRestorer(vault, json_text=True)
    assert restorer.feed('{"k": "\\u27') == '{"k": "'
    assert restorer.feed("e8API_KEY_1") == ""
    assert restorer.feed('\\u27e9"}') == f'{KEY}"}}'
    assert restorer.feed("\\") == "" and restorer.feed("n") == "\\n" and restorer.flush() == ""
    assert restorer.feed("\\u2") == "" and restorer.flush() == "\\u2"       # the stream ended: nothing is lost
