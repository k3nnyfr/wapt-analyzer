# Importer et mettre à jour des paquets

[Documentation](README.md) · commande `import`

## Choisir les paquets

Trois façons de choisir les paquets à importer :

```bash
uv run wapt-analyzer import firefox-esr tis-keepassxc     # par nom, avec ou sans préfixe du store
uv run wapt-analyzer import --from-report wapt-report.json --only gimp,libreoffice-fresh   # candidats d'un rapport JSON
uv run wapt-analyzer import --update                      # paquets du dépôt en retard sur le store
```

## Déroulement

Sans `--apply`, la commande affiche seulement le plan : paquets retenus, dépendances ajoutées, paquets ignorés et pourquoi, taille à télécharger. Avec `--apply`, elle demande confirmation (sauf `-y`) puis exécute :

```bash
uv run wapt-analyzer import firefox-esr --apply           # télécharge, vérifie, signe, envoie
```

Pour chaque paquet :

1. **Téléchargement** depuis le store, avec contrôle MD5 par rapport à l'index.
2. **Vérification** de la signature d'origine : fichiers et métadonnées (`--verify full`, par défaut) ou métadonnées seulement (`--verify control`). Voir [Source et confiance](#source-et-confiance).
3. **Renommage** au préfixe local : `tis-firefox` devient `tsi-firefox`, et les `depends` et `conflicts` suivent.
4. **Signature** avec votre certificat. La passphrase est demandée **une seule fois** : tous les paquets sont signés dans le même processus.
5. **Upload** sur le serveur (`api/v3/upload_packages`), en streaming pour les gros paquets.

Dans un terminal, chaque phase (téléchargement, signature, upload) affiche une barre de progression avec le paquet en cours, ainsi que le débit et le temps restant pour les transferts. Hors terminal (cron, redirection), seuls les messages de log sont écrits.

Comportement par défaut :
- les dépendances absentes de votre dépôt sont ajoutées au plan, sauf avec `--no-deps` ;
- les paquets déjà présents en version égale ou plus récente sont ignorés, sauf avec `--force` ;
- les paquets de l'agent lui-même (`waptupgrade`, `waptsetup`, `waptagent`, `waptserver`) ne sont jamais importés (`[import] exclude`) ;
- les paquets dont la licence contient `wapt_enterprise` ne sont téléchargeables qu'avec un abonnement. Ils sont signalés par un badge « Enterprise » dans le rapport et ignorés par `import`. Si vous avez un abonnement, mettez `[store] restricted_licences = []`.

## Options

Options principales de `wapt-analyzer import` :

| Option | Rôle |
|---|---|
| `PAQUET…` | Paquets à importer (`firefox` ou `tis-firefox`) ; avec `--update`, restreint la mise à jour à ces paquets |
| `--from-report JSON`, `--only` | Importe les candidats d'un rapport JSON, éventuellement filtrés |
| `-i`, `--interactive` | Choisit les paquets dans une liste à cocher (voir [Sélection interactive](#sélection-interactive)) |
| `--update` | Met à jour les paquets du dépôt en retard sur le store (voir ci-dessous) |
| `--apply`, `-y` | Exécute réellement l'import ; `-y` saute la confirmation |
| `--cleanup` | Après l'upload, supprime les versions remplacées par celles importées (voir [Nettoyer le dépôt](cleanup.md)) |
| `--no-deps`, `--force` | Ignore les dépendances ; importe même si le dépôt a déjà la version |
| `--no-upload`, `--output-dir` | Signe sans envoyer ; dossier des paquets signés |
| `--keep-files` | Garde les paquets téléchargés et signés après l'upload (défaut : supprimés une fois envoyés ; `[import] keep_files`) |
| `--certificate`, `--private-key`, `--key-password-file` | Clé de signature (voir plus bas) |
| `--set-maturity` | Maturité des paquets importés (défaut : celle du store) |
| `--verify`, `--trusted-cert`, `--trusted-fingerprint` | Vérification de la source (voir [Source et confiance](#source-et-confiance)) |
| `--wapt-python` | `waptpython` à utiliser (défaut : détection automatique) |

Les options de `report` concernant le serveur, le dépôt, le store et les filtres (`--server`, `--prefix`, `--store-url`, `--os`, `--arch`…) s'appliquent aussi.

## Sélection interactive

Avec `-i` / `--interactive`, la liste est présentée dans le terminal pour cocher les paquets un par un, avant le plan d'import :

```bash
uv run wapt-analyzer import --from-report wapt-report.json -i   # choisir parmi les candidats du rapport
uv run wapt-analyzer import --update -i --apply                 # choisir les mises à jour à appliquer
```

```
Paquets à importer depuis https://wapt.tranquil.it/wapt (4)
Filtre :
 [x] tis-7zip         26.3-46 → 26.4-46                    Windows  x64  1.6 MB    7-Zip
 [-] tis-waptupgrade  2.7.0.19593-0 → 2.7.0.19598-0        Linux    x64  44.4 MB   WAPT Agent  (exclu par la configuration)
 [x] tis-webview2     154.0.4258.62-12 → 155.0.4283.45-12  Windows  x64  204.2 MB  Microsoft Edge WebView2 Runtime
 2 sélectionné(s) sur 4 · ↑↓ déplacer · Espace cocher · Ctrl+A tout · Ctrl+D rien · Entrée valider · Échap annuler
```

- Ce qu'on tape filtre la liste (nom, version, OS, description). `Ctrl+A` et `Ctrl+D` cochent ou décochent les lignes visibles.
- Chaque ligne indique la version (ancienne → nouvelle pour une mise à jour), l'OS, l'architecture, la taille, le nombre de postes concernés (avec `--from-report`) et le nom du logiciel.
- Les paquets réservés aux abonnés ou exclus par `[import] exclude` sont grisés et ne peuvent pas être cochés.
- Avec `--update` ou des noms de paquets, tout est coché au départ. Avec `--from-report`, rien ne l'est, car un rapport propose en général bien plus de paquets qu'on n'en veut.
- `Entrée` valide et affiche le plan d'import (dépendances comprises). `Échap` annule.

## Mettre à jour les paquets du dépôt

```bash
uv run wapt-analyzer import --update                       # plan : paquets en retard sur le store
uv run wapt-analyzer import --update firefox chrome --apply
uv run wapt-analyzer import --update --apply --cleanup     # puis supprime les versions remplacées
```

`--update` reprend la liste de l'onglet « Mises à jour » du rapport : les paquets de votre dépôt pour lesquels le store propose une version plus récente. La comparaison se fait pour le même OS et la même architecture (un paquet local `all` accepte toutes les architectures). Elle porte sur la version complète, donc une nouvelle révision du paquet (`-110` → `-111`) compte aussi. Les noms passés en argument, ou via `--only`, restreignent la liste.

Les paquets mis à jour passent par les mêmes étapes qu'un import : vérification, renommage, signature avec votre clé, upload.

`[import] update_exclude` protège vos paquets maison qui portent le même nom qu'un paquet du store :

```toml
[import]
update_exclude = ["vcredist"]   # nom sans préfixe
```

## Signature

La signature s'appuie sur l'implémentation de référence de WAPT (`waptpackage.sign_package`, comme `wapt-signpackages`), exécutée par le `waptpython` d'un agent WAPT installé :
- `/opt/wapt` sous Linux ;
- `/Applications/wapt` sous macOS ;
- `C:\Program Files (x86)\wapt` sous Windows, y compris depuis WSL.

Le chemin est détecté automatiquement, ou fixé avec `--wapt-python`.

**Sous WSL avec l'agent Windows**, les téléchargements et les paquets signés sont placés sur le disque Windows (`%LOCALAPPDATA%\wapt-analyzer\import`). Les grosses écritures d'un programme Windows vers le partage `\\wsl.localhost\…` peuvent en effet se bloquer indéfiniment. Ce dossier peut être changé avec `[import] work_dir`, à condition de rester sous `/mnt/c/…`.

Chaque paquet envoyé avec succès est ensuite supprimé du dossier de travail, téléchargement et paquet signé, pour ne pas remplir le disque. Les paquets en échec restent en place (le téléchargement est réutilisé au passage suivant), comme tout le résultat de `--no-upload`. `--keep-files` ou `[import] keep_files = true` conserve tout. `purge` vide ce dossier à la demande (voir [Purger les fichiers locaux](cleanup.md#purger-les-fichiers-locaux)).

```toml
[signing]
certificate = "/chemin/vers/moncert.crt"
private_key = "/chemin/vers/moncert.pem"   # défaut : même nom en .pem
```

La passphrase est lue depuis `$WAPT_KEY_PASSWORD` ou un fichier `chmod 600`, sinon demandée une seule fois. Voir [Authentification et secrets](secrets.md#clé-de-signature-et-passphrase) pour l'ordre de recherche et les précautions de stockage.

## Source et confiance

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
