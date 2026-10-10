"""Configuration: built-in defaults < TOML file < environment < command line."""

from __future__ import annotations

import copy
import getpass
import os
import stat
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_CONFIG_PATHS = [
    Path("wapt-analyzer.toml"),
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "wapt-analyzer" / "config.toml",
]

DEFAULTS: dict = {
    "server": {
        "url": "",
        "user": "admin",
        "password_file": "",
        "verify_ssl": True,
        "workers": 8,
        # TLS client certificate, when the server requires one (nginx client certificate authentication)
        "client_certificate": "",
        "client_private_key": "",     # default: client_certificate path with .pem extension if it exists
        "client_key_password_file": "",  # optional, chmod 600, for an encrypted client key
    },
    "repo": {
        "url": "",  # defaults to <server.url>/wapt
        "prefix": "",
    },
    "store": {
        "url": "https://wapt.tranquil.it/wapt",
        "prefix": "tis",
        # Certificates trusted to verify source packages before re-signing them:
        # - fingerprints (SHA-256) of certificates shipped in the source index (ssl/*.crt)
        #   default: the Tranquil IT certificate when the source is the Tranquil IT store, none otherwise
        "trusted_fingerprints": None,
        # - local certificate files or directories, trusted as given
        "trusted_certs": [],
        # Packages carrying these licence tokens cannot be downloaded without a subscription
        # (WAPT Enterprise): they are flagged in the report and skipped by `import`. Set to [] if you have access.
        "restricted_licences": ["wapt_enterprise", "wapt_entreprise"],
    },
    "filters": {
        # OS families to analyse (default: those of the registered hosts)
        "families": [],
        # accepted store package architectures, per OS family
        "architectures": {
            "windows": ["x64", "all", ""],
            "macos": ["arm", "arm64", "x64", "all", ""],
            "linux": ["x64", "all", ""],
        },
        "maturities": ["PROD", ""],
        "locales": ["fr", "en", "all", ""],
    },
    "matching": {
        "threshold": 88,
        # Inventory entries matching these regexes (on the software name) are ignored
        "exclude": [
            r"^(Security )?Update for ",
            r"\bKB\d{6,}\b",
            r"^Microsoft (Visual C\+\+ \d{4}.*)?(Redistributable|Runtime)\b.*\(x86\)",
            r"^Microsoft (Edge Update|Update Health Tools|Windows Desktop Runtime|ASP\.NET Core)",
            r"^Microsoft \.NET (Host|Runtime|AppHost|Toolset|Templates|Workload)",
            r"\b(Drivers?|Pilotes?)\b",
            r"^WAPT",
            r"^Mozilla Maintenance Service",
            r"Add-in for Microsoft Office",
            r"^Microsoft Windows Application Compatibility",
            r"^(Contrôle d.intégrité du PC Windows|Windows PC Health Check)",
            r"^Microsoft (Office File Validation|GameInput|Visual Studio Installer)",
            r"^Windows (Driver Package|SDK|Software Development Kit)",
        ],
        # Regexes on the inventory key (Windows uninstall key, macOS bundle path or pkgid)
        "exclude_keys": [
            r"^/System/",                 # macOS built-in applications
            r"^/Library/Apple/",
            r"^pkgid:",                   # macOS installer receipts, duplicates of the .app entries
        ],
        # Regexes on the publisher
        "exclude_publishers": [r"^apple$"],
        "ignore_system_components": True,
        # Unmatched software from these publisher profiles is folded in the report (shown on demand)
        "fold_profiles": ["oem"],
        # Extra publisher regexes to fold the same way
        "fold_publishers": [],
    },
    # software name regex -> package name without prefix ("" to ignore the software)
    "mappings": {
        r"^Code$": "vscode",                         # Visual Studio Code on macOS
        r"^Visual Studio Code$": "vscode",
    },
    "signing": {
        "certificate": "",            # signer certificate (.crt)
        "private_key": "",            # default: certificate path with .pem extension
        "key_password_file": "",      # optional, chmod 600; otherwise $WAPT_KEY_PASSWORD or prompt
        "wapt_python": "",            # default: auto-detect a WAPT agent's waptpython
    },
    "import": {
        "maturity": "",               # force maturity of imported packages (default: keep the store one)
        "verify": "full",             # full (files + control), control (metadata only) or none (no check)
        "dependencies": True,
        "exclude": ["waptupgrade", "waptsetup", "waptagent", "waptserver"],
        # Packages (name without prefix) never replaced by `import --update`, e.g. your own builds
        "update_exclude": [],
        "work_dir": "",               # default: <cache>/import
    },
    "cleanup": {
        "keep": 0,                    # previous versions kept in addition to the latest
        "exclude": [],                # packages (name without prefix) never cleaned
    },
    "report": {
        "output": "wapt-report.html",
        "json": "",
        "csv_dir": "",
        "language": "fr",
    },
    "cache": {
        "directory": str(Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "wapt-analyzer"),
    },
}


def _merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str | None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    candidates = [Path(path)] if path else DEFAULT_CONFIG_PATHS
    for candidate in candidates:
        if candidate.is_file():
            with candidate.open("rb") as f:
                _merge(cfg, tomllib.load(f))
            cfg["_path"] = str(candidate)
            break
    else:
        if path:
            raise FileNotFoundError(path)
    env = {
        ("server", "url"): "WAPT_SERVER_URL",
        ("server", "user"): "WAPT_USER",
        ("repo", "prefix"): "WAPT_PREFIX",
    }
    for (section, key), var in env.items():
        if os.environ.get(var):
            cfg[section][key] = os.environ[var]
    return cfg


def _read_secret_file(path: str) -> str:
    p = Path(path).expanduser()
    if p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError(f"{p} must not be readable by group/others (chmod 600)")
    return p.read_text(encoding="utf-8").strip()


def _resolve_secret(env: str, file_value: str, env_file: str, prompt: str, missing: str,
                    allow_empty: bool = False) -> str:
    """$ENV, then a protected file (configuration/CLI value, else $ENV_FILE), then an interactive prompt."""
    value = os.environ.get(env)
    if value or (allow_empty and value is not None):
        return value
    path = file_value or os.environ.get(env_file)
    if path:
        return _read_secret_file(path)
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    raise RuntimeError(missing)


def resolve_key_password(cfg: dict) -> str:
    """Private key passphrase, asked once: $WAPT_KEY_PASSWORD (may be empty), a protected passphrase file
    (signing.key_password_file or $WAPT_KEY_PASSWORD_FILE), then an interactive prompt."""
    return _resolve_secret("WAPT_KEY_PASSWORD", cfg["signing"].get("key_password_file"), "WAPT_KEY_PASSWORD_FILE",
                           f"Passphrase for {cfg['signing']['private_key']}: ",
                           "No key passphrase: set WAPT_KEY_PASSWORD, signing.key_password_file "
                           "(or WAPT_KEY_PASSWORD_FILE) or run interactively", allow_empty=True)


def resolve_password(cfg: dict) -> str:
    """Password from $WAPT_PASSWORD, then a protected password file, then an interactive prompt."""
    return _resolve_secret("WAPT_PASSWORD", cfg["server"].get("password_file"), "WAPT_PASSWORD_FILE",
                           f"WAPT password for {cfg['server']['user']}@{cfg['server']['url']}: ",
                           "No password: set WAPT_PASSWORD, server.password_file or run interactively")


def resolve_client_key_password(cfg: dict) -> str:
    """Passphrase of an encrypted TLS client key: $WAPT_CLIENT_KEY_PASSWORD, a protected file
    (server.client_key_password_file or $WAPT_CLIENT_KEY_PASSWORD_FILE), then an interactive prompt."""
    return _resolve_secret("WAPT_CLIENT_KEY_PASSWORD", cfg["server"].get("client_key_password_file"),
                           "WAPT_CLIENT_KEY_PASSWORD_FILE",
                           f"Passphrase for the client key {cfg['server']['client_private_key']}: ",
                           "No client key passphrase: set WAPT_CLIENT_KEY_PASSWORD, "
                           "server.client_key_password_file (or WAPT_CLIENT_KEY_PASSWORD_FILE) or run interactively")


def resolve_totp(cfg: dict) -> str:
    """TOTP code (MFA), asked only when the server requires it: --totp, $WAPT_TOTP, then a prompt.

    A code is valid for about 30 seconds, so it is never read from the configuration file."""
    code = cfg["server"].get("totp") or os.environ.get("WAPT_TOTP")
    if not code and sys.stdin.isatty():
        code = input(f"TOTP code for {cfg['server']['user']}@{cfg['server']['url']}: ")
    if not code:
        raise RuntimeError("This account requires a TOTP code: use --totp, WAPT_TOTP or run interactively")
    code = code.strip()
    if not (code.isdigit() and len(code) == 6):
        raise ValueError("A TOTP code is made of 6 digits")
    return code
