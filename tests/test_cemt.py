import pytest

from dutch_waterways import cemt


@pytest.mark.parametrize(
    "given, code",
    [("V_A", "V_A"), ("Va", "V_A"), ("v a", "V_A"), ("vib", "VI_B"), ("_0", "_0"),
     ("0", "_0"), ("iv", "IV"), (4, "IV"), (0, "_0"), (None, None)],
)
def test_normalize(given, code):
    assert cemt.normalize(given) == code


@pytest.mark.parametrize("bad", ["VIII", "X", "", 11, -1])
def test_normalize_rejects_unknown(bad):
    with pytest.raises(ValueError):
        cemt.normalize(bad)


def test_rank_orders_classes():
    ranks = [cemt.rank(c) for c in cemt.CODES]
    assert ranks == sorted(ranks) == list(range(len(cemt.CODES)))
    assert cemt.rank("Va") > cemt.rank("IV")
