from src.utils import canonical_name


def test_canonical_name_removes_zero_width_and_whitespace():
    raw = " Zero\u200b Width   Name "
    assert canonical_name(raw) == "zero width name"


def test_canonical_name_handles_homoglyphs():
    raw = "M\u0430rio"  # contains Cyrillic small letter a
    assert canonical_name(raw) == "mario"


def test_canonical_name_normalizes_case_and_spacing():
    raw = "Evil   Activities"
    assert canonical_name(raw) == "evil activities"
