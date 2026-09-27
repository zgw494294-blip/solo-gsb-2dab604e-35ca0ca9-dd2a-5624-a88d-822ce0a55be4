"""FastAPI application exposing the offline dependency solver."""

from fastapi import FastAPI

from .schemas import SolveRequest, SolveResponse
from .solver import solve

app = FastAPI(
    title="Offline Dependency Solver",
    summary="Resolve package versions from a self-contained catalog. "
    "No external package repository is ever contacted.",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/solve", response_model=SolveResponse)
def solve_endpoint(request: SolveRequest) -> SolveResponse:
    catalog = {
        name: {
            entry.version: {
                dep: (interval[0], interval[1])
                for dep, interval in entry.dependencies.items()
            }
            for entry in entries
        }
        for name, entries in request.catalog.items()
    }
    roots = {
        name: (interval[0], interval[1]) for name, interval in request.roots.items()
    }

    selected = solve(catalog, roots)
    if selected is None:
        return SolveResponse(satisfiable=False, selected={})
    return SolveResponse(satisfiable=True, selected=selected)
