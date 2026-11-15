"""Authenticated, workspace-scoped v1 research API."""
from fastapi import APIRouter

from umami_api.v1 import identity, projects

router = APIRouter(prefix="/api/v1")
router.include_router(identity.router)
router.include_router(projects.router)
