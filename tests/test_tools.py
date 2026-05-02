import os
import pytest

from marimo_mcp.tools.create import create_notebook_file


def test_create_notebook_file(tmp_path):
    path = str(tmp_path / "new_notebook.py")
    create_notebook_file(path)
    assert os.path.exists(path)
    content = open(path).read()
    assert "import marimo" in content
    assert "marimo.App()" in content
    assert "@app.cell" in content
    assert "app.run()" in content


def test_create_notebook_file_already_exists_raises(tmp_path):
    path = str(tmp_path / "existing.py")
    open(path, "w").write("existing content")
    with pytest.raises(FileExistsError):
        create_notebook_file(path)
