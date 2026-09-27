"""End-to-end tests for POST /conflicts."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def conflicts(payload):
    return client.post("/conflicts", json=payload)


def solve(payload):
    return client.post("/solve", json=payload)


def entry(version, dependencies=None):
    return {"version": version, "dependencies": dependencies or {}}


# --------------------------------------------------------------------------
# Satisfiable requests
# --------------------------------------------------------------------------

def test_satisfiable_with_single_root():
    payload = {
        "catalog": {"app": [entry(1), entry(2)]},
        "roots": {"app": [1, 2]},
    }
    resp = conflicts(payload)
    assert resp.status_code == 200
    assert resp.json() == {
        "satisfiable": True,
        "conflict_roots": [],
        "witnesses": {},
    }


def test_satisfiable_with_multiple_roots():
    payload = {
        "catalog": {
            "a": [entry(1)],
            "b": [entry(1)],
            "c": [entry(1)],
        },
        "roots": {"a": [1, 1], "b": [1, 1], "c": [1, 1]},
    }
    assert conflicts(payload).json() == {
        "satisfiable": True,
        "conflict_roots": [],
        "witnesses": {},
    }


# --------------------------------------------------------------------------
# Minimum unsatisfiable root subset
# --------------------------------------------------------------------------

def test_single_unsatisfiable_root_is_the_conflict():
    payload = {
        "catalog": {"app": [entry(1), entry(2)]},
        "roots": {"app": [3, 4]},
    }
    resp = conflicts(payload)
    # The conflict set has one member; removing it leaves no roots, so its
    # witness is {}.
    assert resp.json() == {
        "satisfiable": False,
        "conflict_roots": ["app"],
        "witnesses": {"app": {}},
    }


def test_smaller_subset_beats_larger_subset():
    # "x" alone is unsatisfiable (no available version); "y" and "z" together
    # are unsatisfiable as a pair, but the singleton is the minimum conflict.
    payload = {
        "catalog": {
            "x": [entry(2)],
            "y": [entry(1)],
            "z": [entry(1, {"y": [2, 2]})],
        },
        "roots": {"x": [1, 1], "y": [1, 1], "z": [1, 1]},
    }
    resp = conflicts(payload)
    assert resp.json() == {
        "satisfiable": False,
        "conflict_roots": ["x"],
        "witnesses": {"x": {}},
    }


def test_pair_conflict_with_each_side_removable():
    # Each root alone is satisfiable; together they clash through shared b.
    # a=1 needs b=1, c=1 needs b=2.
    payload = {
        "catalog": {
            "a": [entry(1, {"b": [1, 1]})],
            "b": [entry(1), entry(2)],
            "c": [entry(1, {"b": [2, 2]})],
        },
        "roots": {"a": [1, 1], "c": [1, 1]},
    }
    resp = conflicts(payload)
    assert resp.json() == {
        "satisfiable": False,
        "conflict_roots": ["a", "c"],
        "witnesses": {
            "a": {"b": 2, "c": 1},
            "c": {"a": 1, "b": 1},
        },
    }


def test_tie_picks_lexicographically_smallest_name_tuple():
    # Two disjoint conflicting pairs: (alpha, beta) and (delta, gamma).
    # Each root alone is satisfiable; each pair alone is unsatisfiable.
    # Iterating sorted names, (alpha, beta) is the first size-2 subset and
    # also the lexicographically smallest name tuple.
    payload = {
        "catalog": {
            "alpha": [entry(1, {"s": [1, 1]})],
            "beta": [entry(1, {"s": [2, 2]})],
            "s": [entry(1), entry(2)],
            "gamma": [entry(1, {"t": [1, 1]})],
            "delta": [entry(1, {"t": [2, 2]})],
            "t": [entry(1), entry(2)],
        },
        "roots": {
            "alpha": [1, 1],
            "beta": [1, 1],
            "gamma": [1, 1],
            "delta": [1, 1],
        },
    }
    resp = conflicts(payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["satisfiable"] is False
    assert body["conflict_roots"] == ["alpha", "beta"]
    assert set(body["witnesses"]) == {"alpha", "beta"}
    # Witnesses use only the other member of the conflicting pair.
    assert body["witnesses"]["alpha"] == {"beta": 1, "s": 2}
    assert body["witnesses"]["beta"] == {"alpha": 1, "s": 1}


def test_innocent_root_is_not_part_of_conflict():
    # "u" is independently satisfiable and irrelevant to the (a, c) clash;
    # witnesses must never include it.
    payload = {
        "catalog": {
            "a": [entry(1, {"b": [1, 1]})],
            "b": [entry(1), entry(2)],
            "c": [entry(1, {"b": [2, 2]})],
            "u": [entry(1)],
        },
        "roots": {"a": [1, 1], "c": [1, 1], "u": [1, 1]},
    }
    body = conflicts(payload).json()
    assert body["conflict_roots"] == ["a", "c"]
    assert body["witnesses"] == {
        "a": {"b": 2, "c": 1},
        "c": {"a": 1, "b": 1},
    }
    for selected in body["witnesses"].values():
        assert "u" not in selected


def test_witness_uses_version_vector_preference():
    # The pair clashes on lib (a forces v1, c forces v2), but c alone may
    # take version 1 or 2; the witness for removing a must pick the solution
    # with the lexicographically largest version vector, i.e. c=2/lib=2.
    payload = {
        "catalog": {
            "a": [entry(1, {"lib": [1, 1]})],
            "c": [
                entry(1, {"lib": [2, 2]}),
                entry(2, {"lib": [2, 2]}),
            ],
            "lib": [entry(1), entry(2)],
        },
        "roots": {"a": [1, 1], "c": [1, 2]},
    }
    body = conflicts(payload).json()
    assert body["satisfiable"] is False
    assert body["conflict_roots"] == ["a", "c"]
    assert body["witnesses"]["c"] == {"a": 1, "lib": 1}
    assert body["witnesses"]["a"] == {"c": 2, "lib": 2}


# --------------------------------------------------------------------------
# Validation is shared with /solve (HTTP 422)
# --------------------------------------------------------------------------

def test_422_on_unknown_root_package():
    payload = {"catalog": {"app": [entry(1)]}, "roots": {"ghost": [1, 1]}}
    assert conflicts(payload).status_code == 422


def test_422_on_empty_roots():
    payload = {"catalog": {"app": [entry(1)]}, "roots": {}}
    assert conflicts(payload).status_code == 422


def test_422_on_inverted_interval():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"app": [2, 1]},
    }
    assert conflicts(payload).status_code == 422


def test_422_on_unknown_top_level_field():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"app": [1, 1]},
        "extra": 1,
    }
    assert conflicts(payload).status_code == 422


def test_solve_endpoint_still_unchanged():
    payload = {
        "catalog": {
            "app": [
                entry(1, {"lib": [1, 2]}),
                entry(2, {"lib": [2, 3]}),
            ],
            "lib": [entry(1), entry(2), entry(3)],
        },
        "roots": {"app": [1, 2]},
    }
    assert solve(payload).json() == {
        "satisfiable": True,
        "selected": {"app": 2, "lib": 3},
    }
