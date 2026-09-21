"""ARPAbet (CMUdict) → IPA. KHÔNG dùng LLM — bản đồ tất định, âm tiết theo nhân nguyên âm.

Đầu ra cho một từ: IPA đầy đủ (có dấu trọng âm + chấm ngăn âm tiết), danh sách IPA
từng âm tiết, và chỉ số âm tiết mang trọng âm chính / phụ.
"""

import re
import unicodedata
from dataclasses import dataclass

# ARPAbet phoneme (đã bỏ chữ số trọng âm) -> IPA (General American, có dấu dài)
_ARPA_IPA = {
    "AA": "ɑː", "AE": "æ", "AH": "ʌ", "AO": "ɔː", "AW": "aʊ", "AY": "aɪ",
    "EH": "ɛ", "ER": "ɜːr", "EY": "eɪ", "IH": "ɪ", "IY": "iː", "OW": "oʊ",
    "OY": "ɔɪ", "UH": "ʊ", "UW": "uː",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p",
    "R": "ɹ", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}
# nguyên âm không trọng âm rút gọn cho tự nhiên hơn
_REDUCED = {"AH": "ə", "ER": "ər"}
_VOWELS = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW",
    "OY", "UH", "UW",
}


@dataclass
class Phoneme:
    ipa: str
    is_vowel: bool
    stress: int  # 0 không · 1 chính · 2 phụ (chỉ nguyên âm)


def _parse(arpabet: list[str]) -> list[Phoneme]:
    out: list[Phoneme] = []
    for token in arpabet:
        stress = 0
        base = token
        if token[-1].isdigit():
            stress = int(token[-1])
            base = token[:-1]
        is_vowel = base in _VOWELS
        if is_vowel and stress == 0 and base in _REDUCED:
            ipa = _REDUCED[base]
        else:
            ipa = _ARPA_IPA.get(base, "")
        out.append(Phoneme(ipa=ipa, is_vowel=is_vowel, stress=stress))
    return out


def _syllable_ranges(phonemes: list[Phoneme]) -> list[tuple[int, int]]:
    nuclei = [i for i, p in enumerate(phonemes) if p.is_vowel]
    if not nuclei:
        return [(0, len(phonemes))]
    ranges: list[tuple[int, int]] = []
    start = 0
    for k in range(len(nuclei) - 1):
        cluster = list(range(nuclei[k] + 1, nuclei[k + 1]))
        split = nuclei[k + 1] if not cluster else cluster[-1]  # phụ âm cuối cụm -> onset kế
        ranges.append((start, split))
        start = split
    ranges.append((start, len(phonemes)))
    return ranges


@dataclass
class Pronunciation:
    ipa: str  # "/ˈbjuː.tɪ.fəl/"
    ipa_syllables: list[str]  # ["ˈbjuː", "tɪ", "fəl"]
    primary_stress: int | None
    secondary_stress: int | None


def arpabet_to_ipa(arpabet: list[str]) -> Pronunciation:
    phonemes = _parse(arpabet)
    ranges = _syllable_ranges(phonemes)
    syllables: list[str] = []
    primary = secondary = None
    for idx, (lo, hi) in enumerate(ranges):
        group = phonemes[lo:hi]
        stress = next((p.stress for p in group if p.is_vowel), 0)
        mark = "ˈ" if stress == 1 else ("ˌ" if stress == 2 else "")
        if stress == 1:
            primary = idx
        elif stress == 2:
            secondary = idx
        syllables.append(mark + "".join(p.ipa for p in group))
    return Pronunciation(
        ipa="/" + ".".join(syllables) + "/",
        ipa_syllables=syllables,
        primary_stress=primary,
        secondary_stress=secondary,
    )


def split_ipa(ipa: str) -> Pronunciation | None:
    """Tách IPA từ điển (EVP) thành âm tiết: ranh giới là '.' hoặc dấu trọng âm ˈ/ˌ (dấu ở đầu âm tiết).
    'ˈbjuːt̬.ɪ.fəl' → ['ˈbjuːt̬','ɪ','fəl'] · 'əˈbɑʊt' → ['ə','ˈbɑʊt']. Không có dấu → 1 âm tiết; rỗng → None."""
    core = ipa.strip().strip("/")
    if not core:
        return None
    parts: list[str] = []
    cur = ""
    for ch in core:
        if ch == ".":
            if cur:
                parts.append(cur)
            cur = ""
        elif ch in "ˈˌ":
            if cur:
                parts.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        parts.append(cur)
    parts = [p for p in parts if p not in ("ˈ", "ˌ")]
    primary = next((i for i, p in enumerate(parts) if p.startswith("ˈ")), None)
    secondary = next((i for i, p in enumerate(parts) if p.startswith("ˌ")), None)
    return Pronunciation(
        ipa="/" + ".".join(parts) + "/",
        ipa_syllables=parts,
        primary_stress=primary,
        secondary_stress=secondary,
    )


_SENTENCE_TOKEN = re.compile(
    r"[^\W\d_]+(?:['’][^\W\d_]+)*(?:-[^\W\d_]+(?:['’][^\W\d_]+)*)*|\d+(?:[.,:]\d+)*|[,.;:!?]"
)
_VOICELESS = set("ptkfθ")
_SIBILANT_TAILS = ("s", "z", "ʃ", "ʒ", "tʃ", "dʒ")


def _strip_accents(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn")


def _word_ipa(word: str, dictionary: dict[str, list[list[str]]]) -> str | None:
    """IPA một từ: tra thẳng → bỏ dấu (café→cafe) → sở hữu cách 's ghép từ gốc + s/z/ɪz."""
    for key in (word, _strip_accents(word)):
        variants = dictionary.get(key)
        if variants:
            return arpabet_to_ipa(variants[0]).ipa.strip("/")
    if word.endswith("'s") and len(word) > 2:
        base = _word_ipa(word[:-2], dictionary)
        if base:
            if base.endswith(_SIBILANT_TAILS):
                return base + "ɪz"
            return base + ("s" if base[-1] in _VOICELESS else "z")
    return None


def sentence_ipa(text: str, dictionary: dict[str, list[list[str]]]) -> str:
    """IPA cả câu từ CMUdict (US), tất định: từng từ nối bằng khoảng trắng, giữ dấu câu để dễ đọc.

    Từ không có trong CMUdict (tên riêng, số…) giữ nguyên chính tả để câu không bị hụt từ;
    từ ghép nối gạch tra từng phần. Từ một âm tiết bỏ dấu trọng âm (trong câu chỉ đánh dấu
    trọng âm từ của từ nhiều âm tiết). Trả "" khi không tra được từ nào.
    """
    out: list[str] = []
    found = 0
    for match in _SENTENCE_TOKEN.finditer(text):
        token = match.group(0)
        if not token[0].isalpha():
            if token[0].isdigit():
                out.append(token)
            elif out:
                out[-1] += token
            continue
        parts = []
        for part in token.replace("’", "'").lower().split("-"):
            ipa = _word_ipa(part, dictionary)
            if ipa:
                if "." not in ipa:
                    ipa = ipa.replace("ˈ", "").replace("ˌ", "")
                parts.append(ipa)
                found += 1
            else:
                parts.append(part)
        out.append("-".join(parts))
    return f"/{' '.join(out)}/" if found else ""
