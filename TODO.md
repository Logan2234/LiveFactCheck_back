# TODO — Backend

Liste de travail estimée à partir de l'état actuel du code. À trier/prioriser.
La source de vérité reste le code, pas ce fichier (cf. CLAUDE.md racine).

## Features métier (nouvelles capacités)

Le produit est aujourd'hui sans état : les claims vivent le temps d'une connexion WS,
rien n'est conservé, un seul utilisateur, vérification figée en français.

- [ ] **Persistance des sessions & claims** : stocker chaque session (transcript + claims vérifiés) en base (SQLite suffit pour commencer) pour pouvoir rejouer, exporter et analyser après coup. Prérequis à la plupart des features ci-dessous.
- [ ] **Export d'une session** : générer un récap (Markdown / PDF / JSON) de tous les claims d'une session — texte, statut, explication, sources, score de confiance.
- [ ] **Historique consultable** : endpoint `/sessions` (liste) + `/sessions/{id}` (détail) pour relire une vérification passée hors live.
- [ ] **Dédoublonnage des claims** : un même fait répété sur plusieurs chunks de 5 s crée aujourd'hui des claims distincts. Détecter les quasi-doublons (similarité du `text`) et fusionner / ne pas re-vérifier — économise des appels Anthropic.
- [ ] **Cache de vérification** : mémoriser le résultat d'un claim déjà vérifié (clé = texte normalisé) pour ne pas repayer un appel sur une affirmation identique.
- [ ] **Webhook / notification sur claim "false"** : pousser une alerte (webhook configurable) quand un fait est démenti, pour intégration externe (overlay OBS, Slack…).
- [ ] **Stats agrégées par session** : ratio vrai/faux/incertain, catégorie dominante, taux de recours au web — exposé en fin de session et dans l'admin.
- [ ] **Multilingue** : rendre `language` (transcription) + le prompt/catégories configurables par session au lieu du français figé.
- [ ] **Niveau de vérification réglable** : exposer côté contrat un mode « rapide » (connaissances internes seules) vs « approfondi » (web_search systématique), au lieu du `web_search=auto` actuel.

## Tests (priorité haute)

Aujourd'hui seul `tests/test_claim_extractor.py` existe. Manquent :

- [ ] `session.py` : tester `_make_claim`, `_spawn_claims` (skip si < `MIN_WORDS`), le cycle pending → claim/remove_claim. Mocker `extract_and_verify` et le `WebSocket`.
- [ ] Auth : `/admin/login` (bon mot de passe → JWT, mauvais → 401), expiration du token, `require_admin` qui rejette un token absent/invalide/expiré.
- [ ] Routes admin : un test d'intégration par route via `TestClient`, avec `require_admin` overridé (`app.dependency_overrides`).
- [ ] `extract_and_verify` : le fallback deux-tours (web_search sans `submit_claims` → second appel forcé). Mocker le client Anthropic.
- [ ] `_parse_claims` : statut invalide → `uncertain`, `confidence` clampée 0-10, champ `text` manquant → claim ignoré.

## Robustesse & sécurité

- [x] CORS : `allow_origins=["*"]` dans `main.py` — restreindre à l'origine du front (via une variable de config `ALLOWED_ORIGINS`) avant tout déploiement.
- [x] Rate-limiting sur `/admin/login` (brute-force du mot de passe admin actuellement libre).
- [x] Vérifier qu'un `.env.example` existe et liste toutes les vars de `config.py` (`ANTHROPIC_*`, `WHISPER_*`, `ADMIN_PASSWORD`, `JWT_SECRET`, `JWT_EXPIRE_HOURS`…) sans valeurs réelles.
- [x] `JWT_SECRET` / `ADMIN_PASSWORD` vides par défaut : faire échouer le démarrage si l'admin est monté sans secret défini (même logique que le validator `ANTHROPIC_API_KEY`).
- [x] Borne la taille des blobs audio reçus sur `/ws` et sur `/admin/whisper/transcribe` (refus si trop gros) pour éviter une saturation mémoire.

## Architecture & dette

- [ ] `_active_sessions` est un dict global au niveau module : OK pour un process unique, mais à documenter comme limite (ne survit pas à plusieurs workers / un restart).
- [ ] Transcription figée en français (`language="fr"`) + prompt/catégories FR : si le multilingue est visé un jour, le rendre configurable.

## Observabilité

- [ ] `/admin/logs` lit un buffer en mémoire (`get_logs`) — vérifier qu'il est borné (pas de fuite mémoire sur longue session).
- [ ] Exposer des métriques agrégées (claims/min, ratio web_search, latence moyenne transcription + vérification) en plus du statut de session brut.
