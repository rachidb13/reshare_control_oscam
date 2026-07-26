from reshare_control.config import (
    AppConfig,
    InstanceConfig,
    UserPolicy,
    create_empty_app_config,
    instance_state_dir,
    load_app_config,
    save_app_config,
    sanitize_instance_id,
    verify_password,
)


def test_create_empty_app_config_generates_admin_password(tmp_path):
    app, password = create_empty_app_config()

    save_app_config(app, str(tmp_path))
    loaded = load_app_config(str(tmp_path))

    assert loaded.web.admin_user == "admin"
    assert verify_password(password, loaded.web.admin_password_hash)
    assert loaded.instances == []


def test_app_config_round_trips_multiple_instances(tmp_path):
    app = AppConfig(instances=[
        InstanceConfig(id="oscam-a", name="OSCam A", host="127.0.0.1", port=8888),
        InstanceConfig(id="oscam-b", name="OSCam B", host="127.0.0.1", port=8889),
    ])

    save_app_config(app, str(tmp_path))
    loaded = load_app_config(str(tmp_path))

    assert [item.id for item in loaded.instances] == ["oscam-a", "oscam-b"]
    assert loaded.get_instance("oscam-b").port == 8889


def test_legacy_single_instance_config_loads_as_app_config(tmp_path):
    legacy = InstanceConfig(host="127.0.0.1", port=8888)
    (tmp_path / "config.json").write_text("{}")
    save_app_config({"host": legacy.host, "port": legacy.port}, str(tmp_path))

    loaded = load_app_config(str(tmp_path))

    assert len(loaded.instances) == 1
    assert loaded.instances[0].host == "127.0.0.1"
    assert loaded.instances[0].id == "default"


def test_sanitize_instance_id_and_state_dir():
    assert sanitize_instance_id("Local OSCam 1!") == "local-oscam-1"
    assert instance_state_dir("/etc/reshare-control", "Local OSCam 1!") == (
        "/etc/reshare-control/instances/local-oscam-1"
    )


def test_instance_config_round_trips_telegram_and_user_policies():
    config = InstanceConfig(
        id="main",
        name="Main",
        host="127.0.0.1",
        port=8888,
        notify_enabled=True,
        telegram_enabled=True,
        telegram_bot_token="123:abc",
        telegram_chat_id="42",
        user_policies={
            "alpha": {"action": "notify", "max_ecm_per_min": "12.5"},
            "bravo": {"action": "ignore"},
        },
    )

    data = config.to_dict()
    loaded = InstanceConfig.from_dict(data)

    assert loaded.telegram_enabled is True
    assert loaded.telegram_bot_token == "123:abc"
    assert loaded.policy_for("alpha").action == "notify"
    assert loaded.policy_for("alpha").max_ecm_per_min == 12.5
    assert loaded.policy_for("bravo").action == "ignore"


def test_user_policy_defaults_to_global():
    policy = UserPolicy.from_dict({})

    assert policy.action == "global"
    assert policy.max_ecm_per_min is None
