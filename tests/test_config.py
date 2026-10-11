import copy

import pytest

from wapt_analyzer.cli import _purge, apply_args, build_parser, cmd_purge
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


@pytest.mark.parametrize("argv, configured, expected", [
    ([], False, False),
    ([], True, True),
    (["--keep-files"], False, True),
])
def test_keep_files(cfg, argv, configured, expected):
    cfg["import"]["keep_files"] = configured
    args = build_parser().parse_args(["import", "firefox", *argv])
    assert apply_args(cfg, args)["import"]["keep_files"] is expected


def test_purge(tmp_path):
    signed, download = tmp_path / "a.wapt", tmp_path / "b.wapt"
    signed.write_bytes(b"x")
    download.write_bytes(b"x")
    _purge(signed, None, download, tmp_path / "missing.wapt")
    assert not signed.exists() and not download.exists()


@pytest.mark.parametrize("apply", [False, True])
def test_purge_command(cfg, tmp_path, apply):
    for sub in ("downloads", "signed", "trusted"):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "a.wapt").write_bytes(b"x" * 10)
    (tmp_path / "signed" / "wapt-analyzer-tmp").mkdir()  # leftover of an interrupted signature
    cfg["import"]["work_dir"] = str(tmp_path)
    args = build_parser().parse_args(["purge", "-y", *(["--apply"] if apply else [])])
    assert cmd_purge(apply_args(cfg, args), args) == 0
    assert (tmp_path / "trusted" / "a.wapt").exists()
    assert (tmp_path / "downloads" / "a.wapt").exists() is not apply
    assert (tmp_path / "signed" / "wapt-analyzer-tmp").exists() is not apply
