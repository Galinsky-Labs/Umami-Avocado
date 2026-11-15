"""Authenticated, workspace-scoped v1 research API."""
from fastapi import APIRouter

from umami_api.v1 import (
    agents,
    evidence,
    governance,
    identity,
    jobs,
    measurements,
    projects,
    simulator,
    spending,
    studio,
)

router = APIRouter(prefix="/api/v1")
router.include_router(identity.router)
router.include_router(projects.router)
router.include_router(governance.router)
router.include_router(measurements.router)
router.include_router(evidence.router)
router.include_router(spending.router)
router.include_router(jobs.router)
router.include_router(simulator.router)
router.include_router(studio.router)
router.include_router(agents.router)
