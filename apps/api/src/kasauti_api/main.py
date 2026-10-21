from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kasauti_api.admin.views import mount_admin
from kasauti_api.api.v1 import auth, practice, pyq
from kasauti_api.settings import get_settings

app = FastAPI(
    title="Kasauti API",
    version="0.1.0",
    description="Delhi-grade preparation, wherever you are.",
)

# The learner app is a separate origin (Next.js on :3000 in dev, its own host in
# prod), so /api/v1 needs CORS. /admin is same-origin and unaffected.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

mount_admin(app)
app.include_router(pyq.router)
app.include_router(auth.build_router())
app.include_router(practice.router)


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    return {"status": "ok", "env": get_settings().env}


# Phase 2 routers land here:
#   app.include_router(evaluations.router, prefix="/api/v1")
#   app.include_router(billing.router, prefix="/api/v1/billing")
