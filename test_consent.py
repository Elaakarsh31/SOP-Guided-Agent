"""Representative authorisation and consent tests. No API key needed."""

import consent


def test_listed_representative_is_found():
    row = consent.authorized("David Chen", "P9")
    assert row["relationship"] == "son"


def test_name_matching_tolerates_case_and_spacing():
    assert consent.authorized("  david   CHEN ", "P9")


def test_representative_of_another_policyholder_is_refused():
    assert consent.authorized("David Chen", "P12") is None


def test_unknown_caller_is_refused():
    assert consent.authorized("Bob Stranger", "P9") is None


def test_missing_arguments_are_refused():
    assert consent.authorized(None, "P9") is None
    assert consent.authorized("David Chen", None) is None


def test_default_scenario_approves_on_the_second_ask():
    assert consent.poll(0, "default") == "pending"
    assert consent.poll(1, "default") == "approved"


def test_denied_scenario_refuses_on_the_second_ask():
    assert consent.poll(0, "denied") == "pending"
    assert consent.poll(1, "denied") == "denied"


def test_timeout_scenario_never_approves():
    statuses = [consent.poll(i, "timeout") for i in range(consent.MAX_POLLS + 1)]
    assert "approved" not in statuses
    assert statuses[-1] == "timeout"


def test_polling_gives_up_at_max_polls():
    assert consent.poll(consent.MAX_POLLS, "default") == "timeout"


def test_unknown_scenario_falls_back_to_default():
    assert consent.poll(1, "no-such-scenario") == "approved"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
