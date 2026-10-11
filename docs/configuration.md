# Configuration

[Documentation](README.md) · suite : [Authentification et secrets](secrets.md)

Toutes les options peuvent être placées dans un fichier TOML, pour ne pas les répéter à chaque commande. L'outil prend le **premier** fichier trouvé parmi :

1. le fichier passé avec `-c` / `--config` (erreur s'il n'existe pas) ;
2. `./wapt-analyzer.toml`, dans le dossier courant ;
3. `~/.config/wapt-analyzer/config.toml` (ou `$XDG_CONFIG_HOME/wapt-analyzer/config.toml`).

Les fichiers ne se cumulent pas : seul le premier trouvé est lu. Sans fichier, les valeurs par défaut s'appliquent.

## Créer le fichier

```bash
mkdir -p ~/.config/wapt-analyzer
cp wapt-analyzer.example.toml ~/.config/wapt-analyzer/config.toml
chmod 600 ~/.config/wapt-analyzer/config.toml
```

Le fichier d'exemple [`wapt-analyzer.example.toml`](../wapt-analyzer.example.toml) liste toutes les clés avec leur valeur par défaut. `wapt-analyzer.toml` est ignoré par git : on peut aussi le placer à la racine du clone.

## Configuration minimale

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

## Sections

| Section | Contenu | Clés principales |
|---|---|---|
| `[server]` | Serveur WAPT et compte admin | `url`, `user`, `password_file`, `verify_ssl` (`true`, `false` ou chemin d'un bundle CA), `workers`, `client_certificate`, `client_private_key`, `client_key_password_file` |
| `[repo]` | Votre dépôt | `prefix`, `url` (défaut : `<server.url>/wapt`) |
| `[store]` | Source des paquets à importer | `url`, `prefix`, `trusted_fingerprints`, `trusted_certs`, `restricted_licences` |
| `[filters]` | Paquets du store retenus | `families`, `maturities`, `locales`, `[filters.architectures]` |
| `[matching]` | Rapprochement logiciel ↔ paquet | `threshold`, `exclude`, `exclude_keys`, `exclude_publishers`, `fold_profiles`, `fold_publishers` |
| `[mappings]` | Corrections manuelles du rapprochement | `"regex" = "paquet"` |
| `[signing]` | Signature des paquets importés | `certificate`, `private_key`, `key_password_file`, `wapt_python` |
| `[import]` | Comportement de `import` | `verify`, `dependencies`, `maturity`, `exclude`, `update_exclude`, `work_dir`, `keep_files` |
| `[hosts]` | Comportement de `hosts` | `exclude` |
| `[groups]` | Comportement de `groups` et `hosts --groups` | `keep_missing`, `suggest_share`, `suggest_min_hosts`, `suggest_name`, `assign_share` |
| `[cleanup]` | Comportement de `cleanup` | `keep`, `exclude`, `unused_min_age` |
| `[deployments]` | Onglet « Déploiements » du rapport et son historique | `stale_days`, `history`, `alert_days` |
| `[report]` | Sorties du rapport | `output`, `json`, `csv_dir`, `language` |
| `[cache]` | Cache local | `directory` |

Le rôle détaillé des options est décrit avec chaque commande : [rapport](report.md), [import](import.md), [nettoyage](cleanup.md), [paquets groupe](groups.md), [paquets machine](hosts.md), [notifications](scheduling.md). Les secrets ont leur page : [Authentification et secrets](secrets.md).

Les chemins de fichiers acceptent `~`.

## Ordre de priorité

Pour une même option, la valeur la plus à droite l'emporte :

> valeurs par défaut < fichier de configuration < variables d'environnement < ligne de commande

| Variable | Équivalent |
|---|---|
| `WAPT_SERVER_URL` | `[server] url` / `--server` |
| `WAPT_USER` | `[server] user` / `--user` |
| `WAPT_PREFIX` | `[repo] prefix` / `--prefix` |
| `WAPT_PASSWORD`, `WAPT_PASSWORD_FILE` | voir [Mot de passe du serveur WAPT](secrets.md#mot-de-passe-du-serveur-wapt) |
| `WAPT_KEY_PASSWORD`, `WAPT_KEY_PASSWORD_FILE` | voir [Clé de signature et passphrase](secrets.md#clé-de-signature-et-passphrase) |
| `WAPT_TOTP` | voir [Double authentification (TOTP)](secrets.md#double-authentification-totp) |
| `WAPT_CLIENT_KEY_PASSWORD`, `WAPT_CLIENT_KEY_PASSWORD_FILE` | voir [Certificat client](secrets.md#certificat-client) |
| `WAPT_SMTP_PASSWORD`, `WAPT_SMTP_PASSWORD_FILE` | voir [Rapport planifié](scheduling.md#planifier-lexécution) |

Les secrets suivent leur propre ordre de recherche, décrit ci-dessous.

## Fichiers créés par l'outil

| Emplacement | Contenu | Remarque |
|---|---|---|
| `~/.cache/wapt-analyzer/` (`[cache] directory`, `--cache-dir`) | Index des dépôts, inventaire des postes, état du dernier envoi de `--notify`, historique des déploiements (`history.sqlite`) | Inventaire et état en `600` ; réutilisés par `report --offline` |
| `<cache>/import/` (`[import] work_dir`) | Paquets téléchargés et signés | Supprimés une fois envoyés (sauf `keep_files`) ; sous WSL avec l'agent Windows : `%LOCALAPPDATA%\wapt-analyzer\import` |
| `wapt-report.html` (`[report] output`, `-o`) | Rapport HTML | Dans le dossier courant par défaut |

L'inventaire en cache décrit vos postes et leurs logiciels : traitez-le comme une donnée interne. On peut supprimer le dossier de cache à tout moment, il est reconstruit au passage suivant.
