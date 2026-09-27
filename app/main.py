"""FastAPI application exposing the offline dependency solver."""

from fastapi import FastAPI

from .schemas import ConflictsResponse, SolveRequest, SolveResponse
from .solver import Catalog, Roots, minimum_conflict_roots, solve

app = FastAPI(
    title="Offline Dependency Solver",
    summary="Resolve package versions from a self-contained catalog. "
    "No external package repository is ever contacted.",
    version="1.1.0",
)


def _parse_request(request: SolveRequest) -> tuple[Catalog, Roots]:
    """Convert validated pydantic payload into the solver's data shapes."""
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
    return catalog, roots


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/solve", response_model=SolveResponse)
def solve_endpoint(request: SolveRequest) -> SolveResponse:
    catalog, roots = _parse_request(request)

    selected = solve(catalog, roots)
    if selected is None:
        return SolveResponse(satisfiable=False, selected={})
    return SolveResponse(satisfiable=True, selected=selected)


@app.post("/conflicts", response_model=ConflictsResponse)
def conflicts_endpoint(request: SolveRequest) -> ConflictsResponse:
    catalog, roots = _parse_request(request)

    if solve(catalog, roots) is not None:
        return ConflictsResponse(
            satisfiable=True, conflict_roots=[], witnesses={}
        )

    conflict_roots = minimum_conflict_roots(catalog, roots)

    # Every witness solves a proper subset of a minimum unsatisfiable set, so
    # it is always satisfiable; ``solve`` never returns None here.
    witnesses: dict[str, dict[str, int]] = {}
    for name in conflict_roots:
        remaining = {
            other: roots[other] for other in conflict_roots if other != name
        }
        witnesses[name] = solve(catalog, remaining) if remaining else {}

    return ConflictsResponse(
        satisfiable=False, conflict_roots=conflict_roots, witnesses=witnesses
    )
