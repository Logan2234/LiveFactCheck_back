# TODO — Backend

Liste de travail estimée à partir de l'état actuel du code. À trier/prioriser.
La source de vérité reste le code, pas ce fichier (cf. CLAUDE.md racine).

## Features métier (nouvelles capacités)

Le produit est aujourd'hui sans état : les claims vivent le temps d'une connexion WS,
rien n'est conservé, un seul utilisateur, vérification figée en français.

- [x] **Persistance des sessions & claims** : SQLAlchemy + SQLite (`app/db/`, modèles `app/models/`). Écriture best-effort au fil de l'eau depuis `session.py` via `app/services/session_store.py` (offload `to_thread`). Le segment porte les mesures de la passe (tokens, latences, `api_calls`, `web_search`) ; tout le reste est dérivé à la lecture. Création **paresseuse** : une session sans aucun transcript ne crée pas de ligne. Réglé par `PERSIST_SESSIONS` (défaut `true`) + `DATABASE_URL`.
- [x] **Export d'une session** : `GET /sessions/{id}/export?format=md|json` (formatteur `app/services/export.py`). PDF non fait (Markdown/JSON seulement).
- [x] **Historique consultable** : `GET /sessions` (liste) + `GET /sessions/{id}` (détail), **gated admin** (`require_admin`).
- [ ] **Dédoublonnage des claims** : un même fait répété sur plusieurs chunks de 5 s crée aujourd'hui des claims distincts. Détecter les quasi-doublons (similarité du `text`) et fusionner / ne pas re-vérifier — économise des appels Anthropic.
- [ ] **Cache de vérification** : mémoriser le résultat d'un claim déjà vérifié (clé = texte normalisé) pour ne pas repayer un appel sur une affirmation identique.
- [ ] **Webhook / notification sur claim "false"** : pousser une alerte (webhook configurable) quand un fait est démenti, pour intégration externe (overlay OBS, Slack…).
- [x] **Stats agrégées par session** : `app/services/stats.py` (`compute_stats`) — ratio par statut, catégorie dominante, confiance moyenne, taux/usage web_search, tokens, latences, rejets, coût € estimé. Exposé dans `/sessions/{id}` et la page admin Sessions. ⚠️ Tarifs `PRICING` dans `stats.py` à vérifier (coût `None` si modèle non tarifé).
- [ ] **Multilingue (prompt Claude)** : la transcription tourne toujours en auto-détection ; la langue choisie par session sert de *filtre* (les chunks d'une autre langue sont ignorés, voir `core/languages.py` + `ConfigMessage` + le filtre dans `session.py`). Reste à adapter `SYSTEM_PROMPT` et l'enum de catégories de `claim_extractor.py` à la langue de la session — actuellement figés FR, donc les claims sortent en français même pour un audio non francophone.
- [x] **Niveau de vérification réglable** : le message WS `config` porte un champ `verification_level` (`fast` / `thorough`, défaut `thorough`). `fast` n'offre pas l'outil `web_search` (un seul appel, connaissances internes) ; `thorough` le rend disponible (comportement antérieur). Plumbing `session.py` → `extract_and_verify(web_search=…)`.

## Tests (priorité haute)

Plusieurs suites existent désormais (`test_claim_extractor`, `test_extract_usage`,
`test_stats`, `test_export`, `test_sessions_route`, `test_session_persistence`,
`test_session_config`, `test_auth_route`…). Restent :

- [ ] `session.py` : `_make_claim`, `_spawn_claims` (skip si < `MIN_WORDS`), le cycle pending → claim/remove_claim. Mocker `extract_and_verify` et le `WebSocket`. (Partiel : `_ensure_persisted` couvert par `test_session_persistence`.)
- [ ] Auth : `/admin/login` (bon mot de passe → JWT, mauvais → 401), expiration du token, `require_admin` qui rejette un token absent/invalide/expiré.
- [ ] Routes admin : un test d'intégration par route via `TestClient`, avec `require_admin` overridé (`app.dependency_overrides`). (Fait pour `/sessions/*` dans `test_sessions_route`.)
- [x] `extract_and_verify` : le fallback deux-tours (web_search sans `submit_claims` → second appel forcé) + accumulation usage/tokens. Couvert par `test_extract_usage` (client Anthropic mocké).
- [x] `_parse_claims` : statut invalide → `uncertain`, `confidence` clampée 0-10, champ `text` manquant → claim ignoré. Couvert par `test_claim_extractor` (`test_unknown_status_falls_back_to_uncertain`, `test_confidence_is_clamped_to_0_10`, `test_entries_without_text_are_dropped`).

## Robustesse & sécurité

- [x] CORS : `allow_origins=["*"]` dans `main.py` — restreindre à l'origine du front (via une variable de config `ALLOWED_ORIGINS`) avant tout déploiement.
- [x] Rate-limiting sur `/admin/login` (brute-force du mot de passe admin actuellement libre).
- [x] Vérifier qu'un `.env.example` existe et liste toutes les vars de `config.py` (`ANTHROPIC_*`, `WHISPER_*`, `ADMIN_PASSWORD`, `JWT_SECRET`, `JWT_EXPIRE_HOURS`…) sans valeurs réelles.
- [x] `JWT_SECRET` / `ADMIN_PASSWORD` vides par défaut : faire échouer le démarrage si l'admin est monté sans secret défini (même logique que le validator `ANTHROPIC_API_KEY`).
- [x] Borne la taille des blobs audio reçus sur `/ws` et sur `/admin/whisper/transcribe` (refus si trop gros) pour éviter une saturation mémoire.

## Architecture & dette

- [x] `_active_sessions` est un dict global au niveau module : OK pour un process unique. Limite documentée en tête de `session.py` — ce n'est pas un cache de la DB (il porte des `asyncio.Task` vivants + une `deque` de contexte non persistés) mais l'état runtime des connexions ouvertes, lu seulement par `/admin/ws/status`. Non remplaçable par des requêtes DB (la base ne sait pas « qui est connecté maintenant »). Reste mono-process : ne survit pas à plusieurs workers / un restart.
- [ ] Transcription : toujours en auto-détection ; la langue par session filtre les chunks (cf. ci-dessus). Le prompt/catégories de fact-checking restent figés FR — voir la ligne « Multilingue (prompt Claude) ».

## Observabilité

- [x] `/admin/logs` lit un buffer en mémoire (`get_logs`) — déjà borné : `_log_history = deque(maxlen=300)` dans `core/observability.py` évince les entrées les plus anciennes, donc pas de fuite mémoire sur longue session.
- [ ] Exposer des métriques agrégées (claims/min, ratio web_search, latence moyenne transcription + vérification) en plus du statut de session brut.
