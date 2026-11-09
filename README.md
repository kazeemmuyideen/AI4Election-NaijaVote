# NaijaVote Navigators

An accessible, nonpartisan civic information service for Nigerian voters. The repository contains a low-bandwidth PWA frontend and a FastAPI backend for cited civic answers, verified polling-unit search, imported hazard advisories, and optional provider integrations.

## Run locally

Requires Python 3.11 or newer.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set a private random ADMIN_API_TOKEN in .env before importing data.
uvicorn backend.app:app --reload --env-file .env
```

Open `http://localhost:8000`. API documentation is at `/docs`; health and data-source status are at `/api/health`. SQLite is created automatically under `data/` by default. Set `DATABASE_PATH` to move it to a persistent volume.

For a container run, use the included `Dockerfile` and `docker-compose.yml` or pass environment variables through your deployment secret manager, and mount a persistent volume at `/app/data`. Do not expose `/docs` or admin endpoints without the production access controls provided by your gateway.

## Current behavior and source guarantees

- Civic answers use a small, curated retrieval set. The API returns its official citation and declines unrelated questions. This is not a comprehensive, continuously synchronized INEC knowledge base.
- English source answers can optionally be translated by an OpenAI-compatible chat-completions endpoint when `LLM_API_KEY` is configured. Translation is constrained to the retrieved answer; the original source citation is retained. Without a translation provider, the UI explicitly displays English rather than inventing legal/electoral translations.
- Polling units are returned only from the local, source-attributed register. No fictitious locations are seeded. If a search has no data, the UI links to INEC's [official polling-unit locator](https://cvr.inecnigeria.org/pu).
- Risk scores come only from current imported hazard reports. “Unknown” means there is no verified report in the local store; it does not mean safe. Imported scores are not a route-safety guarantee.
- Polling-unit proximity checks require coordinates on both the unit and alert, and use the configurable `RISK_PROXIMITY_KM` radius (10 km by default). This is a proximity alert, not floodplain intersection or a dry-route calculation.
- NiMet exposes protected data APIs. Provide the API key and the exact endpoint permitted for your account; `NIMET_ENDPOINT` is deliberately not guessed. The response is shown with retrieval time and the official NiMet source.
- NIHSA feed synchronization accepts an authorized feed normalized to the documented JSON shape below. Full-resolution forecasts may require a subscription. Public NIHSA information remains linked even when no feed is configured.
- Browser speech recognition and speech synthesis depend on the visitor's browser and available voice/language packs.

## Polling-unit data import

Populate `data/polling_units.example.csv` from a reviewed official dataset. Keep the source URL and verification date with every row. Import with the admin token:

```sh
curl -X POST http://localhost:8000/api/admin/import-polling-units \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: text/csv" \
  --data-binary @data/polling_units.example.csv
```

Required CSV headers: `state,lga,ward,name,code,source,source_url,verified_at`. Optional headers: `latitude,longitude,accessibility`. Use HTTPS official source links. Never add voters' names, VINs, phone numbers, or other personal registration data.

## Hazard data

Submit an authorized normalized alert to `POST /api/admin/hazards` with `Authorization: Bearer …` and JSON fields `state`, `hazard`, `severity` (0–100), `details`, `source`, `source_url`, `observed_at`; optional fields are `lga`, `ward`, `latitude`, `longitude`, `expires_at`. Source links must use HTTPS. Expired reports are excluded from lookups.

An optional `NIHSA_FEED_URL` can be synchronized with `POST /api/admin/sync-nihsa`. It must be a trusted HTTPS URL whose JSON response is an array of those normalized alert objects, each citing an official `nihsa.gov.ng` URL. Store feed credentials in `NIHSA_API_TOKEN`, not in source control. Run scheduled synchronization from a protected scheduler and monitor failures.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Database row counts and configured integration status |
| GET | `/api/config` | Supported interface languages and feature status |
| POST | `/api/ask` | Source-cited civic Q&A; body: `{"question":"…","language":"en"}` |
| GET | `/api/polling-units?state=Lagos&lga=Ikeja` | Search only imported verified records |
| GET | `/api/risk?state=Bayelsa&lga=…` | Current imported advisories and highest severity |
| GET | `/api/polling-units/{id}/risk` | Current geolocated alerts within configured proximity of a unit |
| GET | `/api/weather/{state}` | Optional NiMet account endpoint proxy |
| POST | `/api/admin/polling-units` | Add one source-attributed unit (admin bearer token) |
| POST | `/api/admin/import-polling-units` | CSV import (admin bearer token) |
| POST | `/api/admin/hazards` | Add one official-source hazard report (admin bearer token) |
| POST | `/api/admin/knowledge` | Add a reviewed answer, keywords, language and source citation (admin bearer token) |
| POST | `/api/admin/sync-nihsa` | Pull normalized authorized NIHSA feed (admin bearer token) |
| POST | `/api/webhooks/whatsapp` | Twilio-signed inbound WhatsApp webhook |

## Environment settings

See [.env.example](.env.example). Required for data administration: `ADMIN_API_TOKEN`. Optional integrations: `NIMET_API_KEY` + `NIMET_ENDPOINT`, `NIHSA_FEED_URL` + `NIHSA_API_TOKEN`, and `LLM_API_KEY` with optional `LLM_BASE_URL` and `LLM_MODEL`. Twilio inbound webhooks require `TWILIO_AUTH_TOKEN`; set `TWILIO_WEBHOOK_URL` to the exact public HTTPS callback URL when running behind a proxy, register it with Twilio, and enable WhatsApp in your account. Do not commit `.env` or provider credentials.

## Production completion checklist

Before serving a public election, load and audit official polling-unit records, confirm data publication/reuse rights with INEC, obtain and map NiMet account endpoints, contract/authorize the relevant NIHSA feed, have Nigerian-language answers independently reviewed by native civic/legal reviewers, and conduct load, accessibility, privacy, security, and nonpartisanship audits. Production should use PostgreSQL/PostGIS, encrypted managed secrets, backups, rate limits, monitoring, a static asset CDN, and a provider with an explicit SLA. The included SQLite setup is for local development and small demonstrations only. No route is labelled flood-safe until a current hazard dataset, geospatial intersection logic, and field validation are in place.
