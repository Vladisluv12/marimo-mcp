from __future__ import annotations

_TEMPLATE = '''\
import marimo

app = marimo.App()


@app.cell
def __():
    import marimo as mo
    return (mo,)


if __name__ == "__main__":
    app.run()
'''


def create_notebook_file(path: str) -> None:
    import os
    if os.path.exists(path):
        raise FileExistsError(f"File already exists: {path}")
    with open(path, "w") as f:
        f.write(_TEMPLATE)
