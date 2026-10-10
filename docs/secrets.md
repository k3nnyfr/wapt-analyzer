# Authentification et secrets

[Documentation](README.md) · voir aussi : [Configuration](configuration.md)

Les secrets ne se mettent pas dans le fichier de configuration : chacun est lu depuis une variable d'environnement, un fichier protégé (`chmod 600`) ou une saisie au clavier.

## Vue d'ensemble

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

## Limites

- Kerberos n'est pas pris en charge.
- Une tâche planifiée ne peut pas saisir de code TOTP : prévoyez pour elle un compte sans double authentification (voir [Rapport planifié](scheduling.md#prérequis)).
