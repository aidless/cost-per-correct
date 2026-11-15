# CLI 门禁测试：退出码语义 0/1/2/3 必须会红也会绿
import json
import pathlib
import pytest
from costpercorrect.cli import main

FIX_DIR = pathlib.Path(__file__).parent / "fixtures"


def _write_fixtures(tmp_path):
    ok = [{"name": "frontier", "price_in_per_1m": 3.0, "price_out_per_1m": 15.0,
           "tokens_in": 8000, "tokens_out": 2000, "accuracy": 0.95},
          {"name": "composite", "steps": [
              {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
               "tokens_in": 1000, "tokens_out": 400, "accuracy": 0.9},
              {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
               "tokens_in": 500, "tokens_out": 100, "accuracy": 0.7}]}]
    p = tmp_path / "ok.json"
    p.write_text(json.dumps(ok), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"name": "only-one"}]), encoding="utf-8")
    junk = tmp_path / "junk.json"
    junk.write_text("not json{", encoding="utf-8")
    return p, bad, junk


def test退出码0_全部可判(tmp_path):
    p, _, _ = _write_fixtures(tmp_path)
    assert main([str(p)]) == 0


def test退出码2_只有一个方案(tmp_path):
    _, bad, _ = _write_fixtures(tmp_path)
    assert main([str(bad)]) == 2


def test退出码2_坏json(tmp_path):
    _, _, junk = _write_fixtures(tmp_path)
    assert main([str(junk)]) == 2


def test退出码1_带底线有排除(tmp_path):
    p, _, _ = _write_fixtures(tmp_path)
    assert main([str(p), "--min-accuracy", "0.8"]) == 1


def test退出码3_全被排除(tmp_path):
    a = {"name": "a", "price_in_per_1m": 1.0, "price_out_per_1m": 1.0,
         "tokens_in": 1000, "tokens_out": 1000, "accuracy": 0.3}
    b = {"name": "b", "price_in_per_1m": 1.0, "price_out_per_1m": 1.0,
         "tokens_in": 1000, "tokens_out": 1000, "accuracy": 0.2}
    p = tmp_path / "all_low.json"
    p.write_text(json.dumps([a, b]), encoding="utf-8")
    assert main([str(p), "--min-accuracy", "0.5"]) == 3


def test版本标志_与包版本一致(capsys):
    """pip 装完后第一条命令常是 --version：必须能答，且口径与包内 __version__ 一致。"""
    from costpercorrect import __version__

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"cost-per-correct {__version__}"
