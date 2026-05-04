from app.services.cleaner import clean


def test_clean_collapses_whitespace_and_titlecases():
    assert clean("  WHL  MLK  1GAL  ") == "Whl Mlk 1Gal"


def test_clean_preserves_mixed_case():
    assert clean("Coca-Cola") == "Coca-Cola"


def test_clean_handles_lowercase():
    assert clean("organic apples") == "Organic Apples"


def test_clean_empty_string():
    assert clean("   ") == ""
