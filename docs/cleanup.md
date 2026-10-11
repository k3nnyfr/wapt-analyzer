# Nettoyer le dépôt

[Documentation](README.md) · commande `cleanup`

Après une mise à jour, les anciennes versions restent dans le dépôt. `cleanup` supprime celles qu'aucun poste ne peut plus installer :

```bash
uv run wapt-analyzer cleanup                    # simulation : affiche ce qui serait supprimé
uv run wapt-analyzer cleanup firefox --apply    # seulement les anciennes versions de tsi-firefox
uv run wapt-analyzer import --update --apply --cleanup   # mise à jour puis nettoyage dans la foulée
```

La simulation liste chaque version, son OS, son architecture, la version qui la remplace, et l'espace libéré. Les versions conservées malgré tout sont affichées avec leur raison (dépendance à version précise, exclusion, préfixe).

Avec `import --cleanup`, le nettoyage ne porte que sur les paquets qui viennent d'être envoyés, à partir de l'index du dépôt rechargé après l'upload. Il demande la même confirmation, sauf avec `-y`.
Les agents WAPT installent la version la plus élevée parmi celles qui correspondent à leur OS, leur architecture, leur locale, leur maturité et leur version d'OS. Une version n'est donc supprimée que si une version plus récente du même paquet la **couvre entièrement** :

- même maturité ;
- les mêmes OS (ou plus) ;
- une architecture compatible : `all` couvre `x64`, l'inverse non ;
- la même locale (ou `all`) ;
- une plage `min_os_version` / `max_os_version` qui inclut la sienne.

Exemple : si la nouvelle version d'un paquet exige Windows 10 et l'ancienne non, l'ancienne reste, car c'est la dernière installable sur un poste Windows 7.

Garde-fous :
- une version visée par une dépendance à version précise, comme `tsi-foo(=1.2-3)`, n'est pas supprimée ;
- seuls les paquets à votre préfixe sont concernés, sauf avec `--all-prefixes` ;
- `--keep N` conserve en plus les N versions précédentes, pour pouvoir revenir en arrière ;
- `[cleanup] exclude` protège des paquets ;
- les suppressions sont définitives et demandent une confirmation, sauf avec `-y`.

```toml
[cleanup]
keep = 1                      # garde aussi la version précédente
exclude = ["waptupgrade"]     # nom sans préfixe
```

| Option | Rôle |
|---|---|
| `PAQUET…` | Limite le nettoyage à ces paquets (`firefox` ou `tsi-firefox`) |
| `--apply`, `-y` | Supprime réellement ; `-y` saute la confirmation |
| `--keep N` | Conserve en plus les N versions précédentes |
| `--all-prefixes` | Traite aussi les paquets qui ne sont pas à votre préfixe |

## Purger les fichiers locaux

Les paquets téléchargés et signés sont supprimés du dossier de travail dès qu'ils sont envoyés. Restent ceux d'un upload en échec, de `--no-upload` ou de `--keep-files`. `purge` vide les sous-dossiers `downloads/`, `signed/`, `hosts/` et `groups/` du dossier de travail (`[import] work_dir`, voir [Importer et mettre à jour](import.md#signature)). Les certificats de confiance (`trusted/`) sont conservés :

```bash
uv run wapt-analyzer purge              # simulation : contenu de chaque dossier et espace libéré
uv run wapt-analyzer purge --apply -y   # supprime sans confirmation
```

| Option | Rôle |
|---|---|
| `--apply`, `-y` | Supprime réellement ; `-y` saute la confirmation |
| `--cache-dir`, `--wapt-python` | Pour retrouver le dossier de travail par défaut, s'ils diffèrent de la configuration |
