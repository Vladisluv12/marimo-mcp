from __future__ import annotations

import json

from marimo._ast.errors import CycleError, MultipleDefinitionError, UnparsableError
from marimo._session.notebook.file_manager import AppFileManager


def get_deps_static(path: str, cell_id: str | None = None) -> str:
    fm = AppFileManager(path)
    app = fm.app
    try:
        graph = app.graph
    except (CycleError, MultipleDefinitionError):
        graph = app._app._graph
    except UnparsableError as e:
        return json.dumps({"error": str(e)})

    cell_manager = app.cell_manager

    included: set[str]
    if cell_id is not None:
        if cell_id not in graph.cells:
            return json.dumps({"error": f"Cell {cell_id!r} not found"})
        included = graph.ancestors(cell_id) | graph.descendants(cell_id)
        included.add(cell_id)
    else:
        included = set(graph.cells)

    cells = []
    for cd in cell_manager.cell_data():
        cid = cd.cell_id
        if cid not in included or cid not in graph.cells:
            continue
        impl = graph.cells[cid]
        defs = []
        for var in sorted(impl.defs):
            kind = "variable"
            vd_list = impl.variable_data.get(var)
            if vd_list:
                kind = vd_list[-1].kind
            defs.append({"name": var, "kind": kind})
        cells.append({
            "cell_id": cid,
            "cell_name": cd.name,
            "defs": defs,
            "refs": sorted(impl.refs),
            "parent_cell_ids": sorted(graph.parents.get(cid, set())),
            "child_cell_ids": sorted(graph.children.get(cid, set())),
        })

    variable_owners = {
        var: sorted(owners)
        for var, owners in graph.definitions.items()
    }

    multiply_defined = sorted(graph.get_multiply_defined())

    cycles = []
    for cycle_edges in graph.cycles:
        cell_ids: set[str] = set()
        edges = []
        for parent, child in cycle_edges:
            cell_ids.add(parent)
            cell_ids.add(child)
            edges.append([parent, child])
        cycles.append({"cell_ids": sorted(cell_ids), "edges": edges})

    return json.dumps({
        "cells": cells,
        "variable_owners": variable_owners,
        "multiply_defined": multiply_defined,
        "cycles": cycles,
    }, indent=2)


def get_variables_static(path: str) -> str:
    fm = AppFileManager(path)
    app = fm.app
    try:
        graph = app.graph
    except (CycleError, MultipleDefinitionError):
        graph = app._app._graph
    except UnparsableError as e:
        return json.dumps({"error": str(e)})

    variables: list[dict] = []
    seen: set[str] = set()
    for cell_impl in graph.cells.values():
        for var in sorted(cell_impl.defs):
            if var in seen:
                continue
            seen.add(var)
            kind = "variable"
            vd_list = cell_impl.variable_data.get(var)
            if vd_list:
                kind = vd_list[-1].kind
            variables.append({"name": var, "kind": kind})

    return json.dumps({"variables": variables, "note": "Static analysis — values not available without a running session"}, indent=2)
