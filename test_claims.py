"""Claim selection tests. No API key needed."""

import claims

P9 = "P9"


def ids(rows):
    return [c["case_id"] for c in rows]


def test_claims_are_returned_newest_first():
    assert ids(claims.claims_for(P9)) == ["CL-2102", "CL-2048", "CL-1899",
                                          "CL-2011"]


def test_other_peoples_claims_are_never_returned():
    assert "CL-3001" not in ids(claims.claims_for(P9))


def test_spoken_case_id_wins_outright():
    matches, used = claims.find(P9, {"case_id": "cl-2048", "case_type": "auto"})
    assert ids(matches) == ["CL-2048"]
    assert used == ["case_id"]


def test_type_and_status_together_pin_one_claim():
    matches, used = claims.find(P9, {"case_type": "healthcare",
                                     "status": "denied"})
    assert ids(matches) == ["CL-2048"]
    assert used == ["case_type", "status"]


def test_type_alone_can_leave_a_choice():
    matches, _ = claims.find(P9, {"case_type": "healthcare"})
    assert ids(matches) == ["CL-2048", "CL-2011"]


def test_period_accepts_a_month_name_or_a_year_month():
    by_name, used = claims.find(P9, {"period": "january"})
    assert ids(by_name) == ["CL-2048", "CL-2011"]
    assert used == ["period"]
    by_month, _ = claims.find(P9, {"period": "2026-01"})
    assert ids(by_month) == ["CL-2048"]


def test_a_hint_matching_nothing_is_skipped_not_applied():
    """A misremembered month should not wipe out the caller's claims."""
    matches, used = claims.find(P9, {"case_type": "auto", "period": "july"})
    assert ids(matches) == ["CL-2102"]
    assert used == ["case_type"]


def test_unparseable_period_is_ignored():
    matches, used = claims.find(P9, {"period": "a while back"})
    assert len(matches) == 4
    assert used == ["period"]


def test_summary_view_withholds_the_sensitive_fields():
    view = claims.summary_view(claims.get("CL-2048"))
    assert set(view) == {"case_id", "case_type", "status", "created_at"}


def test_contradicts_spots_a_different_claim():
    assert claims.contradicts({"case_type": "auto"}, "CL-2048")
    assert claims.contradicts({"case_id": "CL-2102"}, "CL-2048")
    assert claims.contradicts({"status": "open"}, "CL-2048")


def test_contradicts_allows_a_follow_up_on_the_same_claim():
    assert not claims.contradicts({"case_type": "healthcare"}, "CL-2048")
    assert not claims.contradicts({}, "CL-2048")
    assert not claims.contradicts({"case_type": "auto"}, None)


def test_get_is_case_insensitive_and_safe():
    assert claims.get("cl-2048")["case_id"] == "CL-2048"
    assert claims.get("CL-0000") is None
    assert claims.get(None) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
