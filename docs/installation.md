# Installation

[Documentation](README.md) · suite : [Configuration](configuration.md)

wapt-analyzer s'installe sur un poste d'administration (Linux, macOS, Windows ou WSL) qui accède en HTTPS au serveur WAPT.

## Prérequis

| Besoin | Pour | Détail |
|---|---|---|
| Python 3.10 ou plus récent | toutes les commandes | installé automatiquement par uv si absent |
| [uv](https://docs.astral.sh/uv/) | installation et lancement | recommandé ; `pip` fonctionne aussi |
| Accès HTTPS au serveur WAPT | toutes les commandes | compte administrateur de la console WAPT |
| Accès HTTPS au store (`https://wapt.tranquil.it/wapt` par défaut) | `report`, `import` | ou à la source configurée dans `[store]` |
| Un agent WAPT installé sur la machine | `import` uniquement | fournit le `waptpython` qui signe les paquets |
| Certificat et clé privée de signature WAPT | `import` uniquement | ceux utilisés pour signer vos paquets, reconnus par vos agents |

`report` et `cleanup` n'ont besoin ni de l'agent ni de la clé.

### Agent WAPT (pour `import`)

La signature est faite par le `waptpython` d'un agent WAPT, cherché dans cet ordre :

| Système | Emplacement |
|---|---|
| Linux | `/opt/wapt/waptpython` |
| macOS | `/Applications/wapt/waptpython` |
| WSL | `/mnt/c/Program Files (x86)/wapt/waptpython.exe` (agent Windows de l'hôte) |
| Windows | `C:\Program Files (x86)\wapt\waptpython.exe` |

Si l'agent est ailleurs, indiquez le chemin avec `[signing] wapt_python` ou `--wapt-python`.

Sous WSL avec l'agent Windows, l'outil convertit lui-même les chemins (`wslpath`) et travaille dans `%LOCALAPPDATA%\wapt-analyzer\import` côté Windows. Aucune configuration particulière n'est nécessaire.

## Installer

Le code est publié à deux adresses, au contenu identique :

| Dépôt | URL |
|---|---|
| Gitea (principal) | `https://git.k3nny.fr/k3nny/wapt-analyzer` |
| GitHub (miroir) | `https://github.com/k3nnyfr/wapt-analyzer` |

Les exemples ci-dessous utilisent Gitea ; remplacez l'URL par celle de GitHub si vous préférez.

### Depuis un clone (recommandé)

```bash
git clone https://git.k3nny.fr/k3nny/wapt-analyzer
cd wapt-analyzer
uv run wapt-analyzer --help
```

Le premier `uv run` crée l'environnement virtuel (`.venv/`) et installe les dépendances figées dans `uv.lock`. Les commandes se lancent ensuite toujours depuis ce dossier avec `uv run wapt-analyzer …`.

### En tant qu'outil global

```bash
uv tool install git+https://git.k3nny.fr/k3nny/wapt-analyzer
# ou : uv tool install git+https://github.com/k3nnyfr/wapt-analyzer
wapt-analyzer --help
```

La commande `wapt-analyzer` est alors disponible partout (dans `~/.local/bin`, à ajouter au `PATH` si besoin : `uv tool update-shell`). Dans la suite de la documentation, remplacez `uv run wapt-analyzer` par `wapt-analyzer`.

Pour une version précise : `uv tool install git+https://git.k3nny.fr/k3nny/wapt-analyzer@v0.9.1`.

## Vérifier l'installation

```bash
uv run wapt-analyzer --version
uv run wapt-analyzer report                      # connexion au serveur, inventaire, rapport
uv run wapt-analyzer import firefox              # simulation : vérifie la config d'import sans rien envoyer
```

En cas d'erreur TLS avec un certificat interne, indiquez le bundle de votre autorité : `[server] verify_ssl = "/chemin/vers/ca.pem"` ou `--ca-bundle`. `--insecure` désactive la vérification et n'est à utiliser que pour un test.

## Mise à jour et désinstallation

Depuis un clone :

```bash
git pull
uv run wapt-analyzer --version     # uv resynchronise l'environnement si besoin
```

En outil global :

```bash
uv tool upgrade wapt-analyzer
uv tool uninstall wapt-analyzer
```

La désinstallation ne touche ni à la configuration ni aux secrets. Pour tout supprimer : `rm -r ~/.config/wapt-analyzer ~/.cache/wapt-analyzer`.
