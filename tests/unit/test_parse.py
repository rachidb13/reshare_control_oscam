import os
import hashlib
import json

from reshare_control.parse import NO_READING, normalize_userstats_body


FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


def _fixture(name):
    with open(os.path.join(FIXTURE_DIR, name), "r") as fh:
        return fh.read()


def _users(name, html=None):
    return normalize_userstats_body(_fixture(name), userconfig_html=html)


def test_oscam_userstats_user_array_and_name_username_keys():
    users = _users("userstats_oscam_userstats_array.json")

    assert [user.name for user in users] == ["alpha", "bravo"]
    assert [user.ecm_per_min for user in users] == [24, 8]
    assert all(not user.disabled for user in users)


def test_single_object_is_wrapped():
    users = _users("userstats_single_object.json")

    assert len(users) == 1
    assert users[0].name == "delta"
    assert users[0].ecm_per_min == 5


def test_wrapped_user_entry_is_unwrapped():
    users = _users("userstats_wrapped_user_entry.json")

    assert len(users) == 1
    assert users[0].name == "charlie"
    assert users[0].ecm_per_min == 21


def test_disabled_users_are_skipped():
    assert _users("userstats_disabled_user.json") == []


def test_missing_and_non_numeric_total_ecm_min_are_no_reading():
    missing = _users("userstats_missing_total_ecm_min.json")
    non_numeric = _users("userstats_non_numeric_total_ecm_min.json")

    assert missing[0].name == "foxtrot"
    assert missing[0].ecm_per_min is NO_READING
    assert non_numeric[0].name == "golf"
    assert non_numeric[0].ecm_per_min is NO_READING


def test_hidden_usermd5_resolves_to_alpha_not_idle_decoy():
    users = _users("userstats_hidden_usermd5.json", html=_fixture("userconfig.html"))

    assert len(users) == 1
    assert users[0].name == "alpha"
    assert users[0].usermd5 == "2c1743a391305fbf367df8e4f069f9f9"
    assert users[0].ecm_per_min == 24


def test_oscam_users_shape_resolves_id_prefixed_md5_and_nested_ecm_rate():
    username = "Amiretlgrm@0D97"
    digest = hashlib.md5(username.encode()).hexdigest()
    body = json.dumps({
        "oscam": {
            "users": [
                {"user": {
                    "usermd5": "id_%s" % digest,
                    "status": "online",
                    "classname": "online",
                    "stats": {"n_requ_m": "347"},
                }},
                {"user": {
                    "usermd5": "id_disabled",
                    "status": "offline (disabled)",
                    "classname": "disabled",
                    "stats": {"n_requ_m": "99"},
                }},
            ],
        },
    })
    html = '<td class="usercol1" data-sort-value="%s">%s</td>' % (username, username)

    users = normalize_userstats_body(body, userconfig_html=html)

    assert len(users) == 1
    assert users[0].name == username
    assert users[0].ecm_per_min == 347
    assert users[0].connected is True
