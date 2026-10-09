import copy

import pytest

from wapt_analyzer.config import DEFAULTS, resolve_key_password, resolve_password


@pytest.fixture
def cfg():
    return copy.deepcopy(DEFAULTS)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("WAPT_PASSWORD", "WAPT_PASSWORD_FILE", "WAPT_KEY_PASSWORD", "WAPT_KEY_PASSWORD_FILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)


def secret(tmp_path, name, value, mode=0o600):
    path = tmp_path / name
    path.write_text(value + "\n")
    path.chmod(mode)
    return str(path)


@pytest.mark.parametrize("resolve, section, key, env_file", [
    (resolve_password, "server", "password_file", "WAPT_PASSWORD_FILE"),
    (resolve_key_password, "signing", "key_password_file", "WAPT_KEY_PASSWORD_FILE"),
])
def test_secret_files(cfg, tmp_path, monkeypatch, resolve, section, key, env_file):
    cfg[section][key] = secret(tmp_path, "from-config", "s3cret")
    assert resolve(cfg) == "s3cret"                      # trailing newline stripped

    cfg[section][key] = ""
    monkeypatch.setenv(env_file, secret(tmp_path, "from-env", "other"))
    assert resolve(cfg) == "other"

    cfg[section][key] = secret(tmp_path, "too-open", "x", mode=0o644)
    with pytest.raises(PermissionError, match="chmod 600"):
        resolve(cfg)

    cfg[section][key] = ""
    monkeypatch.delenv(env_file)
    with pytest.raises(RuntimeError):
        resolve(cfg)                                     # no secret and not interactive


def test_env_secret_wins(cfg, tmp_path, monkeypatch):
    cfg["signing"]["key_password_file"] = secret(tmp_path, "kp", "from-file")
    monkeypatch.setenv("WAPT_KEY_PASSWORD", "from-env")
    assert resolve_key_password(cfg) == "from-env"
