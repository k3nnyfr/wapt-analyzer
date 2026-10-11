# Développement

[Documentation](README.md)

## Mise en place

```bash
git clone https://git.k3nny.fr/k3nny/wapt-analyzer && cd wapt-analyzer
uv run ruff check .        # lint
uv run pytest              # tests
```

Les dépendances de développement (`pytest`, `ruff`) sont dans `[dependency-groups]` de `pyproject.toml` : `uv run` les installe automatiquement. La CI (GitHub Actions, reprise par Gitea Actions) lance les mêmes commandes sous Python 3.10, 3.12 et 3.13.

Les tests n'ont besoin ni de serveur WAPT ni d'agent. Ceux du certificat client démarrent un serveur HTTPS local et génèrent leur PKI avec `openssl` ; ils sont ignorés si `openssl` est absent.

## Organisation du code

| Module | Rôle |
|---|---|
| `cli.py` | Commandes et options, enchaînement des étapes |
| `config.py` | Valeurs par défaut, fichier TOML, variables d'environnement, lecture des secrets |
| `server.py` | Client de l'API du serveur WAPT : session TLS (certificat client), login (TOTP), inventaire, paquets machine |
| `fetch.py` | Téléchargements avec cache (index `Packages`, inventaire) |
| `packages.py` | Index `Packages`, versions WAPT, familles d'OS, filtres |
| `analysis.py` | Rapprochement logiciels ↔ paquets, paquets manquants, mises à jour |
| `report.py`, `templates/report.html.j2` | Rapport HTML, JSON et CSV |
| `importer.py` | Plan d'import, vérification de la source, téléchargement, upload |
| `wapt_helper.py` | Script exécuté par le `waptpython` de l'agent : vérification et signature des paquets (implémentation de référence WAPT) |
| `cleanup.py` | Versions supprimables du dépôt |
| `hostpkg.py` | Paquets machine : dépendances à ajouter, reconstruction |
| `actions.py` | Actions à distance sur les agents : cibles, signature, Wake-on-LAN |
| `history.py` | Historique des déploiements (SQLite) : problèmes ouverts, résolus, ancienneté |
| `deploy.py` | Suivi des déploiements : paquets en erreur, installations en attente, postes muets |
| `grouppkg.py` | Paquets groupe : groupes disparus à recréer, groupes suggérés |
| `notify.py` | Résumé du rapport par mail et webhook |
| `picker.py` | Liste à cocher dans le terminal (`-i`) |

## Rapport de démonstration et captures d'écran

```bash
uv run python scripts/demo_report.py -o demo-report.html   # rapport à partir de postes et d'un dépôt fictifs
uv run python scripts/screenshots.py                       # régénère docs/images/*.png
```

`demo_report.py` confronte un dépôt et des postes fictifs à l'index public du store Tranquil IT : aucune donnée réelle n'apparaît. `--offline` réutilise l'index en cache.

`screenshots.py` génère ce rapport puis le photographie avec Chrome ou Chromium sans interface (`$CHROME`, sinon le `PATH`, sinon le Chrome de Windows depuis WSL). Les captures sont définies dans le script : onglet affiché et éventuelles cases cochées.

## Publier une version

1. Mettre à jour `CHANGELOG.md`, `ROADMAP.md` et la version dans `pyproject.toml` et `src/wapt_analyzer/__init__.py`, puis `uv lock`.
2. Commit, tag annoté `vX.Y.Z`, push avec les tags. Le miroir GitHub suit le dépôt Gitea.
