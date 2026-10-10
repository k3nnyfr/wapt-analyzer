# Installation et configuration

Ce guide couvre l'installation de wapt-analyzer, le fichier de configuration et le stockage des secrets (mot de passe du serveur WAPT, code TOTP, certificat client, passphrase de la clé de signature). Pour l'utilisation des commandes, voir le [README](README.md).

- [Prérequis](#prérequis)
- [Installation](#installation)
- [Fichier de configuration](#fichier-de-configuration)
- [Mot de passe du serveur WAPT](#mot-de-passe-du-serveur-wapt)
- [Double authentification (TOTP)](#double-authentification-totp)
- [Certificat client](#certificat-client)
- [Clé de signature et passphrase](#clé-de-signature-et-passphrase)
- [Rapport planifié](#rapport-planifié)
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

Pour une version précise : `uv tool install git+https://git.k3nny.fr/k3nny/wapt-analyzer@v0.7.0`.

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
| `[server]` | Serveur WAPT et compte admin | `url`, `user`, `password_file`, `verify_ssl` (`true`, `false` ou chemin d'un bundle CA), `workers`, `client_certificate`, `client_private_key`, `client_key_password_file` |
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
| `WAPT_TOTP` | voir [Double authentification (TOTP)](#double-authentification-totp) |
| `WAPT_CLIENT_KEY_PASSWORD`, `WAPT_CLIENT_KEY_PASSWORD_FILE` | voir [Certificat client](#certificat-client) |
| `WAPT_SMTP_PASSWORD`, `WAPT_SMTP_PASSWORD_FILE` | voir [Rapport planifié](#rapport-planifié) |

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

## Double authentification (TOTP)

Si le compte WAPT exige un code TOTP, l'outil le demande **seulement quand le serveur le réclame**, après le mot de passe. Le code est cherché dans cet ordre :

1. l'option `--totp CODE` ;
2. la variable d'environnement `WAPT_TOTP` ;
3. une saisie interactive, si l'outil tourne dans un terminal.

```bash
uv run wapt-analyzer report --totp 123456
```

Un code n'est valable qu'une trentaine de secondes : il ne se met donc pas dans le fichier de configuration. L'outil se connecte une seule fois par commande, au début. Même `import --apply` se connecte avant les téléchargements et la signature, pour que le code soit encore valable au moment du login.

Le code est transmis comme le font la console WAPT et `wapt-get` : ajouté au mot de passe sous la forme `motdepasse{123456}`. Un mot de passe qui se termine déjà par `{123456}` est envoyé tel quel.

Une tâche planifiée ne peut pas fournir de code TOTP : utilisez pour elle un compte sans MFA, limité aux droits nécessaires.

## Certificat client

Si le serveur WAPT exige un certificat client (authentification par certificat configurée dans nginx), indiquez-le :

```toml
[server]
client_certificate = "~/.config/wapt-analyzer/client.crt"
client_private_key = "~/.config/wapt-analyzer/client.pem"   # défaut : même chemin en .pem, s'il existe
```

En ligne de commande : `--client-certificate` et `--client-private-key`. Si la clé est dans le même fichier que le certificat, `client_private_key` est inutile.

Le certificat est présenté pour toutes les requêtes vers le serveur : l'API (login, inventaire, upload, suppression) et l'index du dépôt (`<server>/wapt/Packages`). Il ne l'est pas pour le store. Il s'ajoute au login et au mot de passe, il ne les remplace pas.

Si la clé est chiffrée, sa passphrase est cherchée dans cet ordre :

1. la variable `WAPT_CLIENT_KEY_PASSWORD` ;
2. le fichier `--client-key-password-file`, ou à défaut `[server] client_key_password_file` ;
3. le fichier désigné par `WAPT_CLIENT_KEY_PASSWORD_FILE` ;
4. une saisie interactive.

Le fichier suit les mêmes règles que celui du mot de passe : une ligne, `chmod 600`. La clé déchiffrée reste en mémoire et n'est jamais écrite sur disque. Une clé non chiffrée ne déclenche aucune demande ; protégez-la alors en `chmod 600`.

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
| Passphrase du certificat client | `WAPT_CLIENT_KEY_PASSWORD` | `[server] client_key_password_file` / `--client-key-password-file` | `WAPT_CLIENT_KEY_PASSWORD_FILE` |
| Code TOTP | `WAPT_TOTP` | — (`--totp`) | — |
| Mot de passe SMTP | `WAPT_SMTP_PASSWORD` | `[notify.email] password_file` | `WAPT_SMTP_PASSWORD_FILE` |
| URL de webhook | — | `[[notify.webhook]] url_file` | — |

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

## Rapport planifié

`report --notify` envoie le résumé du rapport par mail et/ou webhook (configuration `[notify]` : voir le [README](README.md#rapport-planifié-et-notifications)). Lancé régulièrement, il prévient des nouveautés du parc sans avoir à ouvrir le rapport.

### Prérequis

Une tâche planifiée tourne sans terminal : rien ne peut être saisi au clavier.

- Le mot de passe du serveur doit venir d'un fichier (`[server] password_file`) ou de l'environnement.
- Le compte ne doit pas exiger de code TOTP : prévoyez un compte dédié, sans MFA, limité aux droits nécessaires. `report` ne fait que lire.
- Une clé de certificat client chiffrée demande un fichier de passphrase (`client_key_password_file`).
- Le mot de passe SMTP éventuel vient de `[notify.email] password_file` ou de `WAPT_SMTP_PASSWORD`.
- Une URL de webhook contient souvent un jeton : rangez-la dans un fichier `chmod 600` désigné par `url_file`, plutôt qu'en clair dans `url`.

```bash
install -m 600 /dev/null ~/.config/wapt-analyzer/smtp-password    # puis y écrire le mot de passe SMTP
install -m 600 /dev/null ~/.config/wapt-analyzer/webhook-url      # puis y écrire l'URL du webhook
```

Validez la configuration à la main avant de planifier, sans interroger le serveur : `uv run wapt-analyzer report --offline --notify`.

### Avec cron

`crontab -e`, pour un rapport du lundi au vendredi à 7 h 30 :

```cron
30 7 * * 1-5  $HOME/.local/bin/uv run --directory $HOME/wapt-analyzer wapt-analyzer report --notify --quiet
```

- Le `PATH` de cron est réduit : donnez le chemin complet de `uv` (`which uv`). Avec une installation par `uv tool install`, appelez directement `$HOME/.local/bin/wapt-analyzer`.
- `--directory` pointe vers le clone. La configuration est alors lue dans `./wapt-analyzer.toml` du clone, sinon dans `~/.config/wapt-analyzer/config.toml`.
- `--quiet` n'affiche que les erreurs : cron n'envoie un mail que si quelque chose échoue.
- Pour publier le rapport HTML sur un serveur web, ajoutez `-o /var/www/wapt/wapt-report.html` et renseignez `[notify] report_url`.

### Avec un timer systemd (utilisateur)

`~/.config/systemd/user/wapt-analyzer.service` :

```ini
[Unit]
Description=Rapport wapt-analyzer

[Service]
Type=oneshot
WorkingDirectory=%h/wapt-analyzer
ExecStart=%h/.local/bin/uv run wapt-analyzer report --notify --quiet
```

`~/.config/systemd/user/wapt-analyzer.timer` :

```ini
[Unit]
Description=Rapport wapt-analyzer en semaine

[Timer]
OnCalendar=Mon..Fri 07:30
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now wapt-analyzer.timer
loginctl enable-linger "$USER"        # pour que le timer tourne sans session ouverte
journalctl --user -u wapt-analyzer    # journal des exécutions
```

`Persistent=true` rattrape une exécution manquée, par exemple si la machine était éteinte à l'heure prévue.

### Sous WSL

Ni cron ni systemd ne tournent par défaut dans WSL. Deux possibilités :
- activer systemd dans la distribution (`[boot] systemd=true` dans `/etc/wsl.conf`, puis `wsl --shutdown`), et utiliser le timer ci-dessus ;
- ou créer une tâche dans le Planificateur de tâches Windows qui lance `wsl.exe -d <distribution> -- bash -lc "cd ~/wapt-analyzer && ~/.local/bin/uv run wapt-analyzer report --notify --quiet"`.

## Fichiers créés par l'outil

| Emplacement | Contenu | Remarque |
|---|---|---|
| `~/.cache/wapt-analyzer/` (`[cache] directory`, `--cache-dir`) | Index des dépôts, inventaire des postes, état du dernier envoi de `--notify` | Inventaire et état en `600` ; réutilisés par `report --offline` |
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
