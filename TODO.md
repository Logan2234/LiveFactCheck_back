# TODO — Backend

Liste des features, métier comme tech, à implémenter. La source de vérité reste le code, pas ce fichier.

## Features métier

- [ ] **Dédoublonnage des claims** : un même fait répété sur plusieurs chunks de 5 s crée aujourd'hui des claims distincts. Détecter les quasi-doublons (similarité du `text`) et fusionner / ne pas re-vérifier — économise des appels Anthropic.
- [ ] **Cache de vérification** : mémoriser le résultat d'un claim déjà vérifié (clé = texte normalisé) pour ne pas repayer un appel sur une affirmation identique.
- [ ] **Multilingue (prompt Claude)** : la transcription tourne toujours en auto-détection ; la langue choisie par session sert de *filtre* (les chunks d'une autre langue sont ignorés, voir `core/languages.py` + `ConfigMessage` + le filtre dans `session.py`). Reste à adapter `SYSTEM_PROMPT` et l'enum de catégories de `claim_extractor.py` à la langue de la session — actuellement figés FR, donc les claims sortent en français même pour un audio non francophone.

## Tests (priorité haute)

- [ ] `session.py` : `_make_claim`, `_spawn_claims` (skip si < `MIN_WORDS`), le cycle pending → claim/remove_claim. Mocker `extract_and_verify` et le `WebSocket`. (Partiel : `_ensure_persisted` couvert par `test_session_persistence`.)
- [ ] Auth : `/admin/login` (bon mot de passe → JWT, mauvais → 401), expiration du token, `require_admin` qui rejette un token absent/invalide/expiré.
- [ ] Routes admin : un test d'intégration par route via `TestClient`, avec `require_admin` overridé (`app.dependency_overrides`). (Fait pour `/sessions/*` dans `test_sessions_route`.)

## Observabilité

- [ ] Exposer des métriques agrégées (claims/min, ratio web_search, latence moyenne transcription + vérification) en plus du statut de session brut.
