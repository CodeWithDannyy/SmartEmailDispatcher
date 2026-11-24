import pytest

from dispatcher import ConfigError, Credentials, SecurityMode, SMTPConfig, presets
from dispatcher import config as config_mod


def cfg(**kw):
    base = dict(name="x", host="smtp.gmail.com", port=587, security=SecurityMode.STARTTLS)
    base.update(kw)
    return SMTPConfig(**base)


def test_valid_config_has_no_warnings():
    assert cfg().validate() == []


@pytest.mark.parametrize("host", ["", "   ", "smtp://gmail.com", "smtp.gmail.com/x", "bad host", "-bad.com"])
def test_bad_hosts(host):
    with pytest.raises(ConfigError) as e:
        cfg(host=host).validate()
    assert e.value.field == "host"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "mail.example.co.uk"])
def test_good_hosts(host):
    cfg(host=host).validate()


@pytest.mark.parametrize("port", [0, 70000, -1])
def test_bad_ports(port):
    with pytest.raises(ConfigError) as e:
        cfg(port=port).validate()
    assert e.value.field == "port"


def test_mode_port_mismatch_warns():
    assert any("STARTTLS" in w for w in cfg(port=587, security=SecurityMode.SSL).validate())
    assert any("SSL/TLS" in w for w in cfg(port=465, security=SecurityMode.STARTTLS).validate())
    assert any("Port 25" in w for w in cfg(port=25).validate())


def test_cert_check_off_warns():
    assert any("Certificate" in w for w in cfg(verify_certificate=False).validate())


def test_missing_ca_file():
    with pytest.raises(ConfigError):
        cfg(ca_file="/nope/ca.crt").validate()


def test_presets_are_valid():
    for p in presets():
        p.validate()


def test_profile_roundtrip_never_stores_password(tmp_path, monkeypatch):
    monkeypatch.setenv("SED_CONFIG_DIR", str(tmp_path))
    config_mod.save_profile(cfg(name="Mine", port=465, security=SecurityMode.SSL))
    loaded = config_mod.load_saved_profiles()
    assert loaded[0].name == "Mine" and loaded[0].security is SecurityMode.SSL
    assert "password" not in (tmp_path / "profiles.json").read_text().lower()
    assert config_mod.all_profiles()[0].name == "Mine"


def test_credentials_validation():
    Credentials("a@b.com", "pw").validate()
    for email, pw, field in [("", "pw", "email"), ("nope", "pw", "email"),
                             ("a@b.com", "", "password"), ("a@b.com", " pw", "password")]:
        with pytest.raises(ConfigError) as e:
            Credentials(email, pw).validate()
        assert e.value.field == field


def test_password_hidden_from_repr():
    assert "secret" not in repr(Credentials("a@b.com", "secret"))
