"""HTTP edge: the web-form intake (v1 step 1) and the Prometheus /metrics endpoint.

Like the CLI, this module only asks the composition root for a pipeline and calls it.
Run with: uvicorn triage.api:create_app --factory
"""

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST

from triage import __version__
from triage.container import Container, build_container, build_v1
from triage.contracts import TriageResult
from triage.v1.intake import WebFormSubmission


def create_app(container: Container | None = None) -> FastAPI:
    container = container or build_container()
    v1 = build_v1(container)
    app = FastAPI(title="Service-desk triage", version=__version__)

    @app.post("/tickets")
    def submit_ticket(submission: WebFormSubmission) -> TriageResult:
        """Web-form intake. Unknown or missing fields are rejected with 422 before triage."""
        return v1.pipeline.triage(v1.web_form_intake.receive(submission))

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(container.metrics.exposition(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
