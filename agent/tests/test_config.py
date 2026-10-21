import json

from agent.config import Config, ConfigStore, clamp_scale, data_dir, migrate_legacy


def test_clamp_scale_matches_the_web_ui():
    assert clamp_scale(5) == 2.0
    assert clamp_scale(0.1) == 0.75
    assert clamp_scale(1.234) == 1.25
    assert clamp_scale("nope") == 1.0
    assert clamp_scale(float("nan")) == 1.0


def test_bad_values_fall_back_to_defaults():
    cfg = Config.from_dict(
        {
            "role": "producer",
            "name": 42,
            "prefs": {"theme": "neon", "scale": 9, "vr_mode": 1},
            "osc": {"port": 99999, "host": ""},
            "unknown": True,
        }
    )
    assert cfg.role is None
    assert cfg.name == ""
    assert cfg.prefs.theme == "system"
    assert cfg.prefs.scale == 2.0
    assert cfg.prefs.vr_mode is True
    assert cfg.osc.port == 9000
    assert cfg.osc.host == "127.0.0.1"


def test_round_trip(tmp_path):
    store = ConfigStore(tmp_path)
    store.config.role = "camera"
    store.config.name = "Cam A"
    store.config.prefs.theme = "light"
    store.save()
    again = ConfigStore(tmp_path)
    assert again.config.role == "camera"
    assert again.config.name == "Cam A"
    assert again.config.prefs.theme == "light"
    assert not (tmp_path / "config.tmp").exists()


def test_actor_config_from_v03_sets_the_role(tmp_path):
    legacy = tmp_path / "old"
    legacy.mkdir()
    (legacy / "actor_config.json").write_text(
        json.dumps(
            {
                "server_url": "wss://relay.example/ws",
                "actor_name": "Coda",
                "soundpad_enabled": False,
                "soundpad_path": "D:\\Soundpad\\Soundpad.exe",
                "vrchat_osc_port": 9002,
            }
        )
    )
    store = ConfigStore(tmp_path / "new", legacy_folder=legacy)
    assert store.migrated
    cfg = store.config
    assert (cfg.role, cfg.name, cfg.server_url) == ("actor", "Coda", "wss://relay.example/ws")
    assert cfg.soundpad.enabled is False and cfg.soundpad.path.endswith("Soundpad.exe")
    assert cfg.osc.port == 9002
    assert (tmp_path / "new" / "config.json").exists()


def test_both_v03_files_leave_the_role_open(tmp_path):
    (tmp_path / "actor_config.json").write_text(json.dumps({"server_url": "ws://a"}))
    (tmp_path / "director_config.json").write_text(json.dumps({"server_url": "ws://d", "secret": "s3"}))
    cfg = migrate_legacy(tmp_path)
    assert cfg is not None
    assert cfg.role is None
    assert cfg.secret == "s3"


def test_role_from_the_command_line_keeps_the_secret_out(tmp_path):
    # An actor or camera config never holds the director secret (manual checklist, Windows box)
    (tmp_path / "actor_config.json").write_text(json.dumps({"server_url": "ws://a", "actor_name": "Coda"}))
    (tmp_path / "director_config.json").write_text(json.dumps({"server_url": "ws://d", "secret": "s3"}))
    for role in ("actor", "camera"):
        store = ConfigStore(tmp_path / role, legacy_folder=tmp_path, role=role)
        assert (store.config.role, store.config.secret) == (role, "")
        assert "s3" not in (tmp_path / role / "config.json").read_text()
    director = ConfigStore(tmp_path / "director", legacy_folder=tmp_path, role="director")
    assert (director.config.role, director.config.secret) == ("director", "s3")


def test_existing_config_wins_over_legacy(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"role": "director", "name": "D"}))
    (tmp_path / "actor_config.json").write_text(json.dumps({"actor_name": "Coda"}))
    store = ConfigStore(tmp_path, legacy_folder=tmp_path)
    assert not store.migrated
    assert store.config.role == "director"


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("VRCAS_DATA_DIR", str(tmp_path))
    assert data_dir() == tmp_path
