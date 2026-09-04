"""ARPAbet (CMUdict) → IPA. KHÔNG dùng LLM — bản đồ tất định, âm tiết theo nhân nguyên âm.

Đầu ra cho một từ: IPA đầy đủ (có dấu trọng âm + chấm ngăn âm tiết), danh sách IPA
từng âm tiết, và chỉ số âm tiết mang trọng âm chính / phụ.
"""

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
