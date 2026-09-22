"""Verification gate tests. No API key needed."""

import identity

MARGARET = {"full_name": "Margaret Chen", "dob": "1985-03-15",
            "id_last4": "4472", "phone": "+16505212836",
            "email": "margaret@email.com"}


def test_clean_normalises_spoken_values():
    assert identity.clean("phone", "(650) 521-2836") == "6505212836"
    assert identity.clean("phone", "+1 650 521 2836") == "6505212836"
    assert identity.clean("full_name", "  MARGARET   Chen! ") == "margaret chen"
    assert identity.clean("email", "Margaret@Email.com") == "margaret@email.com"
    assert identity.clean("id_last4", "xxx-xx-0472") == "0472"


def test_clean_rejects_unusable_values():
    assert identity.clean("dob", "March 15 1985") is None
    assert identity.clean("phone", "521-2836") is None
    assert identity.clean("id_last4", "472") is None
    assert identity.clean("full_name", "") is None


def test_three_details_from_one_person_verify():
    result = identity.check({k: MARGARET[k]
                             for k in ("full_name", "dob", "id_last4")})
    assert result["verified"]
    assert result["party_id"] == "P9"
    assert result["mismatched"] == []


def test_two_details_are_not_enough():
    result = identity.check({"full_name": "Margaret Chen", "dob": "1985-03-15"})
    assert not result["verified"]
    assert result["still_needed"] == ["phone", "email", "id_last4"]


def test_details_borrowed_from_three_people_do_not_verify():
    """A name, a dob and an id from three different policyholders."""
    result = identity.check({
        "full_name": "Margaret Chen",   # P9
        "dob": "1990-08-21",            # Ava Lopez, P7
        "id_last4": "6688",             # Ma Tian, P12
    })
    assert not result["verified"]
    assert len(result["matched"]) == 1
    assert sorted(result["mismatched"]) == ["dob", "id_last4"]


def test_pinned_party_ignores_another_persons_correct_detail():
    result = identity.check({"full_name": "Margaret Chen", "dob": "1990-08-21"},
                            party_id="P9")
    assert result["party_id"] == "P9"
    assert result["matched"] == ["full_name"]
    assert result["mismatched"] == ["dob"]


def test_policy_number_is_not_a_verification_factor():
    assert "policy_number" not in identity.FIELDS
    result = identity.check({"full_name": "Margaret Chen", "dob": "1985-03-15",
                             "policy_number": "POL-9921"})
    assert not result["verified"]


def test_wrong_value_is_reported_as_mismatched():
    result = identity.check({"full_name": "Margaret Chen", "id_last4": "0000"})
    assert result["mismatched"] == ["id_last4"]
    assert "id_last4" in result["still_needed"]


def test_person_lookup():
    assert identity.person("P9")["name"] == "Margaret Chen"
    assert identity.person("nobody") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
