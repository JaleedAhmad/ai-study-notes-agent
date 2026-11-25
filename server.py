"""Native Streamlit server; launch with streamlit run server.py."""

from pathlib import Path

import streamlit as st
from starlette.responses import JSONResponse
from starlette.routing import Route


async def health(request):
    """Process liveness only; do not query providers or expose application state."""
    return JSONResponse({"status": "ok"})


app = st.App(
    str(Path(__file__).resolve().with_name("app.py")),
    routes=[Route("/health", health, methods=["GET"], name="health")],
)
