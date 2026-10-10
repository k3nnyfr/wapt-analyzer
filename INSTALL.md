# Installation et configuration

Ce guide couvre l'installation de wapt-analyzer, le fichier de configuration et le stockage des secrets (mot de passe du serveur WAPT, passphrase de la clé de signature). Pour l'utilisation des commandes, voir le [README](README.md).

- [Prérequis](#prérequis)
- [Installation](#installation)
- [Fichier de configuration](#fichier-de-configuration)
- [Mot de passe du serveur WAPT](#mot-de-passe-du-serveur-wapt)
- [Clé de signature et passphrase](#clé-de-signature-et-passphrase)
- [Fichiers créés par l'outil](#fichiers-créés-par-loutil)
- [Vérifier l'installation](#vérifier-linstallation)
- [Mise à jour et désinstallation](#mise-à-jour-et-désinstallation)

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

## Installation

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
wapt-analyzer --help
```

La commande `wapt-analyzer` est alors disponible partout (dans `~/.local/bin`, à ajouter au `PATH` si besoin : `uv tool update-shell`). Dans la suite de la documentation, remplacez `uv run wapt-analyzer` par `wapt-analyzer`.

Pour une version précise : `uv tool install git+https://git.k3nny.fr/k3nny/wapt-analyzer@v0.4.1`.

## Fichier de configuration

Toutes les options peuvent être placées dans un fichier TOML, pour ne pas les répéter à chaque commande. L'outil prend le **premier** fichier trouvé parmi :

1. le fichier passé avec `-c` / `--config` (erreur s'il n'existe pas) ;
2. `./wapt-analyzer.toml`, dans le dossier courant ;
3. `~/.config/wapt-analyzer/config.toml` (ou `$XDG_CONFIG_HOME/wapt-analyzer/config.toml`).

Les fichiers ne se cumulent pas : seul le premier trouvé est lu. Sans fichier, les valeurs par défaut s'appliquent.

### Créer le fichier

```bash
mkdir -p ~/.config/wapt-analyzer
cp wapt-analyzer.example.toml ~/.config/wapt-analyzer/config.toml
chmod 600 ~/.config/wapt-analyzer/config.toml
```

Le fichier d'exemple [`wapt-analyzer.example.toml`](wapt-analyzer.example.toml) liste toutes les clés avec leur valeur par défaut. `wapt-analyzer.toml` est ignoré par git : on peut aussi le placer à la racine du clone.

### Configuration minimale

Pour `report` et `cleanup` :

```toml
[server]
url = "https://wapt.example.org"
user = "admin"
password_file = "~/.config/wapt-analyzer/password"

[repo]
prefix = "tsi"             # préfixe de vos paquets
```

Pour `import`, ajoutez la clé de signature :

```toml
[signing]
certificate = "~/wapt-keys/moncert.crt"
private_key = "~/wapt-keys/moncert.pem"
key_password_file = "~/.config/wapt-analyzer/key-password"
```

### Sections

| Section | Contenu | Clés principales |
|---|---|---|
| `[server]` | Serveur WAPT et compte admin | `url`, `user`, `password_file`, `verify_ssl` (`true`, `false` ou chemin d'un bundle CA), `workers` |
| `[repo]` | Votre dépôt | `prefix`, `url` (défaut : `<server.url>/wapt`) |
| `[store]` | Source des paquets à importer | `url`, `prefix`, `trusted_fingerprints`, `trusted_certs`, `restricted_licences` |
| `[filters]` | Paquets du store retenus | `families`, `maturities`, `locales`, `[filters.architectures]` |
| `[matching]` | Rapprochement logiciel ↔ paquet | `threshold`, `exclude`, `exclude_keys`, `exclude_publishers`, `fold_profiles`, `fold_publishers` |
| `[mappings]` | Corrections manuelles du rapprochement | `"regex" = "paquet"` |
| `[signing]` | Signature des paquets importés | `certificate`, `private_key`, `key_password_file`, `wapt_python` |
| `[import]` | Comportement de `import` | `verify`, `dependencies`, `maturity`, `exclude`, `update_exclude`, `work_dir` |
| `[cleanup]` | Comportement de `cleanup` | `keep`, `exclude` |
| `[report]` | Sorties du rapport | `output`, `json`, `csv_dir`, `language` |
| `[cache]` | Cache local | `directory` |

Le rôle détaillé de chaque option est décrit dans le [README](README.md), section par section.

Les chemins de fichiers acceptent `~`.

### Ordre de priorité

Pour une même option, la valeur la plus à droite l'emporte :

> valeurs par défaut < fichier de configuration < variables d'environnement < ligne de commande

| Variable | Équivalent |
|---|---|
| `WAPT_SERVER_URL` | `[server] url` / `--server` |
| `WAPT_USER` | `[server] user` / `--user` |
| `WAPT_PREFIX` | `[repo] prefix` / `--prefix` |
| `WAPT_PASSWORD`, `WAPT_PASSWORD_FILE` | voir [Mot de passe du serveur WAPT](#mot-de-passe-du-serveur-wapt) |
| `WAPT_KEY_PASSWORD`, `WAPT_KEY_PASSWORD_FILE` | voir [Clé de signature et passphrase](#clé-de-signature-et-passphrase) |

Les secrets suivent leur propre ordre de recherche, décrit ci-dessous.

## Mot de passe du serveur WAPT

Le mot de passe du compte admin est cherché dans cet ordre, la première source trouvée est utilisée :

1. la variable d'environnement `WAPT_PASSWORD` (ignorée si vide) ;
2. le fichier `--password-file`, ou à défaut `[server] password_file` ;
3. le fichier désigné par `WAPT_PASSWORD_FILE` ;
4. une saisie interactive, si l'outil tourne dans un terminal.

Hors terminal (cron, CI) sans aucune de ces sources, la commande s'arrête avec une erreur.

### Créer le fichier de mot de passe

```bash
install -m 600 /dev/null ~/.config/wapt-analyzer/password   # crée le fichier vide, déjà en 600
${EDITOR:-nano} ~/.config/wapt-analyzer/password            # y écrire le mot de passe, seul sur la ligne
```

Le fichier contient uniquement le mot de passe ; les espaces et retours à la ligne en début et en fin sont ignorés. Évitez `echo 'motdepasse' > fichier` : la commande resterait dans l'historique du shell.

**Le fichier est refusé s'il est lisible par le groupe ou les autres** (`must not be readable by group/others (chmod 600)`). Corriger avec :

```bash
chmod 600 ~/.config/wapt-analyzer/password
```

### Variable d'environnement

Pratique pour une session ponctuelle, sans laisser de trace dans l'historique :

```bash
read -rs WAPT_PASSWORD && export WAPT_PASSWORD
uv run wapt-analyzer report
```

Pour une tâche planifiée, préférez un fichier `chmod 600` à une variable écrite en clair dans la crontab ou un script.

### Cas particuliers

- **WSL** : rangez les fichiers de secrets dans le système de fichiers Linux (`~/…`), pas sous `/mnt/c/…`. Les fichiers du disque Windows apparaissent en général avec les droits `777`, et `chmod` n'y a pas d'effet sans l'option de montage `metadata` : ils sont donc refusés.
- **Windows natif** : les droits Unix n'existent pas et les fichiers paraissent lisibles par tous, donc refusés. Utilisez `WAPT_PASSWORD` ou la saisie interactive.

## Clé de signature et passphrase

`import` signe les paquets avec **votre** certificat, celui auquel vos agents WAPT font confiance. Il faut :

- le certificat (`.crt`) : `[signing] certificate` ou `--certificate` ;
- la clé privée (`.pem`) : `[signing] private_key` ou `--private-key`. Par défaut, le même chemin que le certificat avec l'extension `.pem`.

Ce sont les fichiers utilisés par la console WAPT pour signer vos paquets. Gardez la clé privée avec des droits restreints (`chmod 600`) et hors du dépôt git (les extensions `.pem`, `.key`, `.crt` et `.p12` sont ignorées par le `.gitignore`).

### Passphrase de la clé

Elle est demandée **une seule fois** par import, même pour plusieurs paquets, et cherchée dans cet ordre :

1. la variable d'environnement `WAPT_KEY_PASSWORD`. Une valeur vide est acceptée : c'est le cas d'une clé non chiffrée (`WAPT_KEY_PASSWORD= uv run wapt-analyzer import …`) ;
2. le fichier `--key-password-file`, ou à défaut `[signing] key_password_file` ;
3. le fichier désigné par `WAPT_KEY_PASSWORD_FILE` ;
4. une saisie interactive, si l'outil tourne dans un terminal.

Le fichier de passphrase suit les mêmes règles que celui du mot de passe : une seule ligne, `chmod 600` obligatoire, même création :

```bash
install -m 600 /dev/null ~/.config/wapt-analyzer/key-password
${EDITOR:-nano} ~/.config/wapt-analyzer/key-password
```

Rangez-le **ailleurs que la clé privée**, et hors de tout dossier synchronisé ou sauvegardé avec elle : une passphrase qui voyage à côté de la clé chiffrée ne protège plus rien. Pour un usage interactif, la saisie au clavier reste l'option la plus sûre.

La passphrase est transmise au processus `waptpython` par son entrée standard, jamais sur la ligne de commande ni dans un fichier.

### Récapitulatif des secrets

| Secret | Variable | Fichier (config / CLI) | Variable de fichier |
|---|---|---|---|
| Mot de passe du serveur | `WAPT_PASSWORD` | `[server] password_file` / `--password-file` | `WAPT_PASSWORD_FILE` |
| Passphrase de la clé | `WAPT_KEY_PASSWORD` | `[signing] key_password_file` / `--key-password-file` | `WAPT_KEY_PASSWORD_FILE` |

Arborescence type :

```
~/.config/wapt-analyzer/
├── config.toml        # 600 — configuration
├── password           # 600 — mot de passe du compte admin WAPT
└── key-password       # 600 — passphrase de la clé (facultatif)
~/wapt-keys/           # ailleurs : certificat et clé privée
├── moncert.crt
└── moncert.pem        # 600
```

## Fichiers créés par l'outil

| Emplacement | Contenu | Remarque |
|---|---|---|
| `~/.cache/wapt-analyzer/` (`[cache] directory`, `--cache-dir`) | Index des dépôts, inventaire des postes | Fichiers en `600` ; réutilisés par `report --offline` |
| `<cache>/import/` (`[import] work_dir`) | Paquets téléchargés et signés | Sous WSL avec l'agent Windows : `%LOCALAPPDATA%\wapt-analyzer\import` |
| `wapt-report.html` (`[report] output`, `-o`) | Rapport HTML | Dans le dossier courant par défaut |

L'inventaire en cache décrit vos postes et leurs logiciels : traitez-le comme une donnée interne. On peut supprimer le dossier de cache à tout moment, il est reconstruit au passage suivant.

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
