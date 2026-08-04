"""FastAPI application.

Read-only by design. There is no endpoint that places a bet, and none that
contacts a bookmaker account — the API only exposes analyses the engine already
produced. The Challenge endpoints mutate local simulation state and require an
explicit confirmation call before a step advances.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from betmaxxing import DISCLAIMER, __version__
from betmaxxing.api.routes import challenges, health, scans, settings_routes
from betmaxxing.config import get_settings

DESCRIPTION = """
Betmaxxing — aide à la décision pour paris sportifs prématch.

**Cette API ne place aucun pari**, ne se connecte à aucun compte de bookmaker et
ne déclenche aucune transaction. Elle expose des analyses probabilistes assorties
de leur incertitude, de leur qualité de données et de leur statut de validation.

Un scan retourne toujours l'un de trois statuts : `CANDIDATES_FOUND`, `NO_BET`
(résultat normal) ou `DATA_UNAVAILABLE`.
"""


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Betmaxxing API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=[
            {"name": "health", "description": "Santé du service et des fournisseurs."},
            {"name": "scans", "description": "Lancement et consultation des scans."},
            {"name": "challenges", "description": "Challenge — Montante (simulation)."},
            {"name": "settings", "description": "Configuration effective et seuils."},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(scans.router)
    app.include_router(challenges.router)
    app.include_router(settings_routes.router)

    @app.get("/", tags=["health"])
    def root() -> dict[str, str]:
        return {
            "name": "Betmaxxing",
            "version": __version__,
            "mode": str(settings.mode),
            "disclaimer": DISCLAIMER,
            "docs": "/docs",
        }

    return app


app = create_app()
