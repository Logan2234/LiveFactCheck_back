# LiveFactChecker — Backend

API de fact-checking audio en temps réel. Reçoit des chunks audio via WebSocket,
les transcrit en local avec **faster-whisper**, puis extrait et vérifie les
affirmations factuelles avec l'**API Claude d'Anthropic** (web search inclus).

## Stack

| Composant     | Techno                                         |
| ------------- | ---------------------------------------------- |
| Framework     | FastAPI + uvicorn                              |
| Transcription | faster-whisper (local, via ffmpeg)             |
| Fact-checking | Anthropic Claude API (`tool_use` + web search) |
| Validation    | Pydantic + pydantic-settings                   |
| Formatage     | Ruff                                           |

## Prérequis

- Python 3.10+
- **ffmpeg** disponible dans le `PATH` (faster-whisper l'utilise pour décoder
  les blobs WebM/Opus envoyés par le frontend)
- Une clé API Anthropic

## Installation

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # puis renseignez ANTHROPIC_API_KEY
```

## Lancer

```bash
python run.py
# ou directement :
python -m uvicorn app.main:app --reload
```

L'API écoute sur `http://localhost:8000`. `run.py` active `--reload` et
surveille aussi les changements de `.env`.

## Variables d'environnement (`.env`)

| Variable            | Défaut                      | Description                                        |
| ------------------- | --------------------------- | -------------------------------------------------- |
| `ANTHROPIC_API_KEY` | _(obligatoire)_             | Clé API Anthropic                                  |
| `ANTHROPIC_MODEL`   | `claude-haiku-4-5-20251001` | Modèle Claude utilisé pour le fact-checking        |
| `WHISPER_MODEL`     | `medium`                    | `tiny` \| `base` \| `small` \| `medium` \| `large` |
| `WHISPER_DEVICE`    | `cpu`                       | `cpu` \| `cuda`                                    |
| `LOG_LEVEL`         | `INFO`                      | Niveau de log des loggers applicatifs (`app.*`)    |

Le démarrage échoue volontairement si `ANTHROPIC_API_KEY` est absente ou laissée
à sa valeur placeholder (validateur dans [`app/config.py`](app/config.py)).

## Endpoints

| Méthode | Route         | Rôle                                                           |
| ------- | ------------- | -------------------------------------------------------------- |
| `GET`   | `/health`     | Healthcheck (`{"status": "ok"}`)                               |
| `POST`  | `/fact-check` | Fact-check d'un texte brut (`{"text": "..."}`)                 |
| `WS`    | `/ws`         | Flux audio temps réel (chunks WebM/Opus) → transcript + claims |

## Flux WebSocket `/ws`

1. Le frontend enregistre des tranches de ~5 s avec `MediaRecorder` et envoie
   chaque tranche comme un blob WebM/Opus complet (frame binaire).
2. Chaque blob est transcrit en une passe par faster-whisper (exécuté dans un
   thread pour ne pas bloquer la boucle async).
3. Le transcript est renvoyé (`{"type": "transcript", ...}`), puis le
   fact-checking est lancé en tâche de fond.
4. Pour chaque chunk : un claim `pending` est émis, puis remplacé par le résultat
   vérifié, ou retiré (`remove_claim`) si aucun fait n'a été trouvé.

> ⚠️ Les phrases peuvent être coupées entre deux chunks de 5 s — c'est la
> méthode de référence simple. Une transcription en flux continu pourra
> remplacer ça plus tard.

## Structure

```text
backend/
├── run.py                       # point d'entrée uvicorn (reload + watch .env)
├── requirements.txt
├── .env.example
└── app/
    ├── main.py                  # app FastAPI + endpoints uniquement
    ├── config.py                # Settings (.env) + validation
    ├── models/
    │   └── schemas.py           # modèles Pydantic (Claim, VerificationStatus, ...)
    └── services/
        ├── session.py           # orchestration d'une connexion WebSocket
        ├── transcription.py     # faster-whisper (transcribe_chunk)
        └── claim_extractor.py   # Claude API : tool_use submit_claims + web_search
```

## Formatage

```bash
ruff format .
ruff check .
```
