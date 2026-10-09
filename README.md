# wapt-analyzer

Outil en ligne de commande qui compare le dépôt de paquets d'un serveur [WAPT](https://www.wapt.fr), le store public Tranquil IT et l'inventaire des postes, pour **suggérer les paquets manquants**.

Il produit un rapport HTML autonome (avec export JSON/CSV optionnel) contenant :

| Onglet | Contenu |
|---|---|
| **Paquets manquants** | Paquets WAPT installés sur les postes mais absents du dépôt, quel que soit le préfixe (`tis-firefox` ≈ `tsi-firefox`), avec leur disponibilité dans le store |
| **À importer** | Logiciels installés hors WAPT pour lesquels un paquet existe dans le store |
| **Hors WAPT** | Logiciels installés hors WAPT alors qu'un paquet existe déjà dans le dépôt |
| **Sans équivalent** | Logiciels pour lesquels aucun paquet n'a été identifié |
| **Mises à jour** | Paquets du dépôt dont la version amont est plus ancienne que celle du store |
| **Liste d'import** | Liste consolidée des paquets du store à importer |

Dans le rapport, chaque paquet proposé (onglets paquets manquants, à importer, mises à jour, liste d'import) a une case à cocher. Une barre en bas de page affiche la commande `uv run wapt-analyzer import …` correspondant à la sélection, regroupée par OS, prête à copier. Les paquets réservés aux abonnés ne sont pas sélectionnables.

La commande `report` ne fait que **lire**. La commande `import` importe ensuite les paquets choisis depuis le store : elle les re-signe avec **votre** clé et les envoie sur votre serveur.

## Installation

Python 3.10 ou plus récent.

Avec [uv](https://docs.astral.sh/uv/), depuis un clone (l'environnement est créé automatiquement au premier `uv run`) :

```bash
git clone https://git.k3nny.fr/k3nny/wapt-analyzer && cd wapt-analyzer
uv run wapt-analyzer --help
```

Ou en tant qu'outil installé globalement :

```bash
uv tool install git+https://git.k3nny.fr/k3nny/wapt-analyzer
wapt-analyzer --help
```

## Utilisation

```bash
export WAPT_PASSWORD='…'          # sinon le mot de passe est demandé
uv run wapt-analyzer report --server https://wapt.example.org --user admin --prefix tsi
```

Options principales de `wapt-analyzer report` :

| Option | Rôle |
|---|---|
| `--server URL` | URL du serveur WAPT |
| `--user`, `--password-file` | Compte admin ; le fichier de mot de passe doit être en `chmod 600` |
| `--prefix` | Préfixe de vos paquets (ex. `tsi`) |
| `--repo-url`, `--store-url`, `--store-prefix` | Dépôt local (défaut `<server>/wapt`) et store (défaut Tranquil IT, préfixe `tis`) |
| `--os` | Familles d'OS analysées : `windows`, `macos`, `linux` (défaut : celles des postes) |
| `--arch`, `--maturity`, `--locale` | Filtres sur les paquets du store, valeurs séparées par des virgules |
| `--threshold` | Score minimal (0–100) du rapprochement logiciel ↔ paquet, 88 par défaut |
| `-o`, `--json`, `--csv-dir` | Sorties HTML, JSON et CSV |
| `--offline` | Réutilise les index et l'inventaire mis en cache lors du dernier passage |
| `--insecure`, `--ca-bundle` | Vérification TLS |
| `-v`, `-vv` | Verbosité |

### Configuration

Toutes les options peuvent être placées dans un fichier TOML : `./wapt-analyzer.toml`, `~/.config/wapt-analyzer/config.toml` ou le fichier passé avec `-c`. Voir [`wapt-analyzer.example.toml`](wapt-analyzer.example.toml).

Ordre de priorité : valeurs par défaut < fichier < variables d'environnement (`WAPT_SERVER_URL`, `WAPT_USER`, `WAPT_PREFIX`, `WAPT_PASSWORD`, `WAPT_PASSWORD_FILE`) < ligne de commande.

### Ajuster le rapprochement

Le lien entre le nom d'un logiciel dans l'inventaire et un paquet est heuristique : nom normalisé (sans version, architecture ni langue), puis correspondance floue. La section `[mappings]` permet de corriger le résultat :

```toml
[mappings]
"^Microsoft Teams" = "microsoft-teams-uwp"   # force le paquet (nom sans préfixe)
"^ACME outil interne" = ""                    # ignore ce logiciel
```

Les **éditions** ne sont jamais mélangées. Un numéro qui identifie une édition (« Office 2016 », « Microsoft 365 », « Visual C++ v14 ») doit se retrouver dans le paquet proposé. Les versions à points, les architectures et les numéros de build ou d'update ne comptent pas comme des éditions. Si aucun paquet de la même édition n'existe, le logiciel est classé « sans équivalent » et le rapport liste les autres éditions disponibles. On peut alors en choisir une avec un mapping.

Un nom d'éditeur générique en tête (« Microsoft », « Adobe »…) est aussi essayé sans l'éditeur, car les noms du store l'omettent souvent : « Microsoft Office LTSC Professional Plus 2021 » est rapproché de « Office LTSC Professional Plus 2021 ».

`[matching] exclude` contient la liste des expressions régulières qui écartent du bruit (mises à jour KB, pilotes, runtimes…).

### Multi-OS (Windows, macOS, Linux)

L'analyse est faite par famille d'OS, déterminée à partir de l'OS du poste et du champ `target_os` des paquets. Un paquet `tsi-firefox` publié pour Windows ne couvre donc pas un Mac. Le store est filtré par architecture selon la famille (`[filters.architectures]`). Quand un logiciel n'a pas de paquet pour son OS mais en a un pour un autre, le rapport l'indique.

Sur macOS, l'inventaire est filtré par défaut : applications système (`/System/…`), reçus d'installation `pkgid:` et éditeur `apple`.

### Comment l'outil reconnaît un logiciel installé par WAPT

Un logiciel est considéré comme installé par WAPT dans deux cas :
- sa clé de désinstallation figure dans le champ `uninstall_key` d'un paquet installé sur le poste ;
- le paquet auquel il est rapproché est installé par WAPT sur ce poste. C'est le cas typique sur macOS, où les paquets ne déclarent en général pas de clé.

Les autres sont traités comme installés hors WAPT.

## Importer des paquets depuis le store

```bash
uv run wapt-analyzer import firefox-esr tis-keepassxc     # simulation : affiche le plan
uv run wapt-analyzer import --from-report wapt-report.json --only gimp,libreoffice-fresh
uv run wapt-analyzer import firefox-esr --apply           # télécharge, signe, envoie
uv run wapt-analyzer import --update                      # met à jour les paquets en retard sur le store
uv run wapt-analyzer import --update firefox chrome --apply
```

`--update` reprend la liste de l'onglet « Mises à jour » du rapport : les paquets de votre dépôt pour lesquels le store propose une version plus récente. La comparaison se fait pour le même OS et la même architecture (un paquet local `all` accepte toutes les architectures). Elle porte sur la version complète, donc une nouvelle révision du paquet (`-110` → `-111`) compte aussi. Les noms passés en argument, ou via `--only`, restreignent la liste. `[import] update_exclude` protège vos paquets maison qui portent le même nom qu'un paquet du store.

Pour chaque paquet, avec `--apply` :

1. **Téléchargement** depuis le store, avec contrôle MD5 par rapport à l'index.
2. **Vérification** de la signature d'origine : fichiers et métadonnées (`--verify full`, par défaut) ou métadonnées seulement (`--verify control`). Voir [Source et confiance](#source-et-confiance).
3. **Renommage** au préfixe local : `tis-firefox` devient `tsi-firefox`, et les `depends` et `conflicts` suivent.
4. **Signature** avec votre certificat. La passphrase est demandée **une seule fois** : tous les paquets sont signés dans le même processus.
5. **Upload** sur le serveur (`api/v3/upload_packages`), en streaming pour les gros paquets.

Dans un terminal, chaque phase (téléchargement, signature, upload) affiche une barre de progression avec le paquet en cours, ainsi que le débit et le temps restant pour les transferts. Hors terminal (cron, redirection), seuls les messages de log sont écrits.

Comportement par défaut :
- les dépendances absentes de votre dépôt sont ajoutées au plan, sauf avec `--no-deps` ;
- les paquets déjà présents en version égale ou plus récente sont ignorés, sauf avec `--force` ;
- `--no-upload` produit seulement les paquets signés, dans `--output-dir`.
- les paquets dont la licence contient `wapt_enterprise` ne sont téléchargeables qu'avec un abonnement. Ils sont signalés par un badge « Enterprise » dans le rapport et ignorés par `import`. Si vous avez un abonnement, mettez `[store] restricted_licences = []`.

La signature s'appuie sur l'implémentation de référence de WAPT (`waptpackage.sign_package`, comme `wapt-signpackages`), exécutée par le `waptpython` d'un agent WAPT installé :
- `/opt/wapt` sous Linux ;
- `/Applications/wapt` sous macOS ;
- `C:\Program Files (x86)\wapt` sous Windows, y compris depuis WSL.

Le chemin est détecté automatiquement, ou fixé avec `--wapt-python`.

```toml
[signing]
certificate = "/chemin/vers/moncert.crt"
private_key = "/chemin/vers/moncert.pem"   # défaut : même nom en .pem
```

Ordre de recherche de la passphrase : `$WAPT_KEY_PASSWORD`, puis `key_password_file` (chmod 600), puis saisie interactive.

### Source et confiance

La source par défaut est le store public Tranquil IT, mais n'importe quel dépôt WAPT peut servir de source (dépôt interne, miroir…) via `--store-url` et `--store-prefix`.

Avant de signer un paquet avec votre clé, l'outil vérifie qu'il est authentique. Sont considérés comme dignes de confiance :

- les **certificats locaux** listés dans `trusted_certs` (fichiers ou dossiers), acceptés tels quels ;
- les certificats **fournis dans l'index de la source** (`ssl/*.crt`), uniquement si leur empreinte SHA-256 figure dans `trusted_fingerprints`.

Par défaut, seul le certificat Tranquil IT (`8c5127a7…`) est épinglé, et seulement quand la source est le store Tranquil IT. L'index de ce store contient aussi un certificat `CN=test`, qui n'est donc pas accepté.

Pour une autre source sans confiance configurée, l'import s'arrête avant de demander la moindre passphrase et affiche les certificats trouvés dans l'index, avec leur empreinte, pour qu'on puisse en épingler un en connaissance de cause.

```toml
[store]
url = "https://wapt.interne.lan/wapt"
prefix = "abc"
trusted_fingerprints = ["b4cbf9ee…"]          # certificat fourni dans l'index de la source
trusted_certs = ["/etc/wapt/ssl/interne.crt"]  # et/ou certificats locaux
```

En ligne de commande : `--trusted-fingerprint SHA256` et `--trusted-cert CHEMIN` (options répétables).

`--verify none` désactive toute vérification. À n'utiliser que si vous maîtrisez totalement la source : les paquets seront signés avec votre clé sans aucun contrôle.

## Limites

- Le serveur WAPT ne conserve que l'état **actuel** des paquets sur chaque poste. Un paquet désinstallé disparaît de l'inventaire, et l'historique est donc partiel.
- L'authentification se fait pour l'instant uniquement par login et mot de passe : pas de MFA, pas de certificat client (voir la [roadmap](ROADMAP.md)).

## Développement

```bash
uv run ruff check .
uv run pytest
```

## Licence

[GPL-3.0-or-later](LICENSE), comme WAPT.
