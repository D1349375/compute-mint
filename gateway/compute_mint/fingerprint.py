"""Content fingerprints: exact-data matching in the spirit of DLP.

Path rules label what was read from a named file. They cannot label text that merely *contains*
the same data in another place: a failing test prints customer names that were read, in another
session, from `config/clients.json`. This index remembers distinctive terms of sensitive content
(names, identifiers, numbers) and recognizes them again in later text.

What is remembered, per source (a file path): not the text, only keyed 64-bit hashes of terms,
with the source they came from. The key is random per process and the index lives in memory only;
nothing here is written to a log, the ledger, the policy database or any request. A hit is
resolved to a label at lookup time from the source's *current* label, so a file the user later
reviews as public stops protecting anything.

Terms (all case-folded), with the weight of a hit when the source is known to be sensitive (a rule or a
credential file says so) / when it merely has not been reviewed yet:
  id       an identifier of 6+ characters mixing letters and 3+ digits (`ab12345678`), a decimal with 4+
           places (`0.1375`)                                                                     2 / 2
  name     two consecutive capitalized words, at least one of them not common (`jane doe`)       2 / 2
  word     an unusual word: 8+ letters, not in `common_words.txt`                                2 / 0
  weak     a capitalized unusual 5-7 letter word, a digit string of 6+, a decimal with 3 places  1 / 0
A message is a match when the distinct hits score 2 or more. An unreviewed source is weaker evidence (most
files are not sensitive, and ordinary vocabulary would otherwise block unrelated work), so only its names and
identifiers count.
Prose (`.md`, `.txt`, ...) contributes unusual words only when capitalized in mid-sentence (proper nouns).
Source code contributes only the contents of its string literals and numeric constants: identifiers are shared
between files and say nothing about sensitivity. Words the caller already has in its own prompt are exempt, so
the project's own name never trips the index. Terms that also occur in a file the user cleared
(a rule below CONFIDENTIAL) do not count either: they may leave anyway.
"""
import hashlib
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

IDENT, NAME, WORD, WEAK = "I", "N", "S", "W"
SCORE = {IDENT: 2, NAME: 2, WORD: 2, WEAK: 1}          # sources known to be sensitive
SCORE_UNREVIEWED = {IDENT: 2, NAME: 2, WORD: 0, WEAK: 0}
THRESHOLD = 2
MAX_TERMS_PER_SOURCE = 20_000
MAX_TERMS = 400_000

_ATOM = re.compile(r"[^\W_]+", re.UNICODE)
_SEGMENT_BREAK = re.compile(r"""[\r\n\t,;:|(){}\[\]<>"=/\\]+|[.!?]+(?=\s|$)""")
_DECIMAL = re.compile(r"(?<![\w.])\d+\.\d{3,}(?![\w])")
_TRIPLE_QUOTED = re.compile(r'"""[\s\S]*?"""' + "|" + r"'''[\s\S]*?'''")
_STRING_LITERAL = re.compile(r'"(?:\\.|[^"\\\n]){3,}"|\'(?:\\.|[^\'\\\n]){3,}\'')
PROSE_EXTENSIONS = frozenset(".md .rst .txt .adoc .tex .html .htm".split())
CODE_EXTENSIONS = frozenset(".py .pyi .js .jsx .mjs .cjs .ts .tsx .java .kt .go .rs .rb .php .c .h .cc .cpp .hpp .cs .swift "
                            ".scala .lua .sh .bash .ps1 .bat".split())

_COMMON: frozenset[str] | None = None


def common_words() -> frozenset[str]:
    global _COMMON
    if _COMMON is None:
        path = Path(__file__).with_name("common_words.txt")
        _COMMON = frozenset(path.read_text(encoding="utf-8").split())
    return _COMMON


def is_code_path(path: str) -> bool:
    return os.path.splitext(path.lower())[1] in CODE_EXTENSIONS


def is_prose_path(path: str) -> bool:
    return os.path.splitext(path.lower())[1] in PROSE_EXTENSIONS


def _is_cap(word: str) -> bool:
    return word[:1].isupper() and (not word.isupper() or len(word) >= 6)


def _ident_atom(a: str) -> bool:
    digits = sum(c.isdigit() for c in a)
    return len(a) >= 6 and digits >= 3 and digits < len(a) and a.isalnum()


def extract(text: str, code: bool = False, prose: bool = False) -> dict[str, str]:
    """Distinctive terms of `text` -> kind. `code` keeps only string literals and numeric constants;
    `prose` accepts unusual single words only when capitalized in mid-sentence."""
    if code:
        literals = [m.group(0)[1:-1] for m in _STRING_LITERAL.finditer(_TRIPLE_QUOTED.sub(" ", text))]
        scope = "\n".join(literals) + "\n" + "\n".join(_DECIMAL.findall(text))
    else:
        scope = text
    out: dict[str, str] = {}

    def put(term: str, kind: str) -> None:
        if SCORE[kind] > SCORE.get(out.get(term, ""), 0):
            out[term] = kind

    common = common_words()
    for d in _DECIMAL.findall(scope):
        put(d, IDENT if len(d.split(".")[1]) >= 4 else WEAK)
    for segment in _SEGMENT_BREAK.split(scope):
        words = _ATOM.findall(segment)
        folded = [w.casefold() for w in words]
        for k, (w, a) in enumerate(zip(words, folded)):
            if _ident_atom(a):
                if a not in common:
                    put(a, IDENT)
            elif a.isalpha() and a not in common:
                mid_sentence_proper = _is_cap(w) and k > 0
                if len(a) >= 8 and (not prose or mid_sentence_proper):
                    put(a, WORD)
                elif 5 <= len(a) <= 7 and _is_cap(w) and (not prose or k > 0):
                    put(a, WEAK)
            elif a.isdigit() and len(a) >= 6:
                put(a, WEAK)
        for (w1, a1), (w2, a2) in zip(zip(words, folded), zip(words[1:], folded[1:])):
            if (len(a1) >= 3 and len(a2) >= 3 and a1.isalpha() and a2.isalpha() and _is_cap(w1) and _is_cap(w2)
                    and not (a1 in common and a2 in common)):
                put(a1 + " " + a2, NAME)
        if len(out) > MAX_TERMS_PER_SOURCE:
            break
    return out


def probe_terms(text: str) -> list[str]:
    """Every term of `text` that could be in the index: atoms of 4+ characters, adjacent pairs, decimals."""
    seen: dict[str, None] = {}
    for d in _DECIMAL.findall(text):
        seen[d] = None
    for segment in _SEGMENT_BREAK.split(text):
        folded = [w.casefold() for w in _ATOM.findall(segment)]
        for a in folded:
            if len(a) >= 4:
                seen[a] = None
        for a1, a2 in zip(folded, folded[1:]):
            if len(a1) >= 3 and len(a2) >= 3:
                seen[a1 + " " + a2] = None
    return list(seen)


@dataclass(frozen=True)
class Match:
    kind: str
    sources: tuple[str, ...]


class FingerprintIndex:
    def __init__(self, threshold: int = THRESHOLD) -> None:
        self.threshold = threshold
        self._key = os.urandom(16)
        self._terms: dict[bytes, tuple[str, set[str]]] = {}
        self._added: set[tuple[str, bytes]] = set()
        self._cleared: set[bytes] = set()
        self._cleared_texts: set[bytes] = set()
        self._probe_cache: OrderedDict[bytes, list[bytes]] = OrderedDict()

    def __repr__(self) -> str:   # never show content, not even hashed
        return f"<FingerprintIndex terms={len(self._terms)} sources={len({s for _, ss in self._terms.values() for s in ss})}>"

    def _h(self, term: str) -> bytes:
        return hashlib.blake2b(term.encode("utf-8"), key=self._key, digest_size=8).digest()

    def add(self, source: str, text: str, code: bool | None = None, prose: bool | None = None) -> int:
        """Remember the distinctive terms of `text`, read from `source`. Returns the number of new terms."""
        if code is None:
            code = is_code_path(source)
        if prose is None:
            prose = is_prose_path(source)
        digest = hashlib.blake2b(text.encode("utf-8"), key=self._key, digest_size=8).digest()
        if (source, digest) in self._added:
            return 0
        self._added.add((source, digest))
        new = 0
        for term, kind in extract(text, code, prose).items():
            if len(self._terms) >= MAX_TERMS:
                break
            h = self._h(term)
            known = self._terms.get(h)
            if known is None:
                self._terms[h] = (kind, {source})
                new += 1
            else:
                best = kind if SCORE[kind] > SCORE[known[0]] else known[0]
                self._terms[h] = (best, known[1] | {source})
        return new

    def clear(self, text: str) -> None:
        """Terms of a text the user has cleared (a file with a rule below CONFIDENTIAL) stop counting as evidence:
        they are already allowed to leave, so repeating them elsewhere reveals nothing new."""
        digest = hashlib.blake2b(text.encode("utf-8"), key=self._key, digest_size=8).digest()
        if digest not in self._cleared_texts and len(self._cleared) < MAX_TERMS:
            self._cleared_texts.add(digest)
            self._cleared.update(self._probe(text))

    def _probe(self, text: str) -> list[bytes]:
        key = hashlib.blake2b(text.encode("utf-8"), key=self._key, digest_size=16).digest()
        hit = self._probe_cache.get(key)
        if hit is not None:
            self._probe_cache.move_to_end(key)
            return hit
        hashes = [self._h(t) for t in probe_terms(text)]
        self._probe_cache[key] = hashes
        if len(self._probe_cache) > 256:
            self._probe_cache.popitem(last=False)
        return hashes

    def exempt_set(self, *texts: str) -> frozenset[bytes]:
        """Terms the caller itself supplied (prompt, system message): never evidence of a leak."""
        return frozenset(h for t in texts for h in self._probe(t))

    def matches(self, text: str, exempt: frozenset[bytes] = frozenset()) -> list[Match]:
        out = []
        for h in self._probe(text):
            entry = self._terms.get(h)
            if entry is not None and h not in exempt and h not in self._cleared:
                out.append(Match(entry[0], tuple(sorted(entry[1]))))
        return out

    def __len__(self) -> int:
        return len(self._terms)
