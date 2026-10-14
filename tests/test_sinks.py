import json

import pytest

from shopify_pipeline.sinks.jsonl import write_jsonl


def test_write_jsonl(tmp_path):
    out = tmp_path / "sub" / "orders.jsonl"
    n = write_jsonl([{"id": 1, "name": "#1001 ñ"}, {"id": 2}], out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert n == 2
    assert json.loads(lines[0]) == {"id": 1, "name": "#1001 ñ"}


def test_write_jsonl_atomico_no_deja_parcial(tmp_path):
    def gen():
        yield {"id": 1}
        raise RuntimeError("fallo a mitad")

    out = tmp_path / "orders.jsonl"
    with pytest.raises(RuntimeError):
        write_jsonl(gen(), out)
    assert not out.exists()
    assert list(tmp_path.iterdir()) == []
