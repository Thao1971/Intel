"""Regression checks for exact procurement counts; no database connection required."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

BACKEND = Path(__file__).resolve().parents[1]
FILES = ("server.py", "routes/procurement.py", "services/placsp_connector.py",
         "services/procurement_connector.py")


def count_calls():
    for filename in FILES:
        tree = ast.parse((BACKEND / filename).read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "count_documents"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "public_procurement_contracts"):
                yield filename, node


def run_count(node, query):
    collection = SimpleNamespace(count_documents=AsyncMock(return_value=659486))
    db = SimpleNamespace(public_procurement_contracts=collection)
    function = ast.AsyncFunctionDef(
        name="run", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
        kw_defaults=[], defaults=[]), body=[ast.Return(value=ast.Await(value=node))],
        decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {"db": db, "query": query}
    exec(compile(module, "<procurement-count-regression>", "exec"), namespace)
    return asyncio.run(namespace["run"]()), collection.count_documents


class ExactProcurementCountTests(unittest.TestCase):
    def test_all_unfiltered_counts_use_existing_index_and_keep_exact_result(self):
        calls = [(f, n) for f, n in count_calls()
                 if n.args and isinstance(n.args[0], ast.Dict) and not n.args[0].keys]
        self.assertEqual(len(calls), 6)
        for filename, node in calls:
            with self.subTest(file=filename, line=node.lineno):
                result, call = run_count(node, {})
                self.assertEqual(result, 659486)
                call.assert_awaited_once_with({}, hint="_id_")

    def list_count(self):
        return next(n for f, n in count_calls() if n.args
                    and isinstance(n.args[0], ast.Name) and n.args[0].id == "query")

    def test_empty_list_search_has_exact_indexed_total(self):
        result, call = run_count(self.list_count(), {})
        self.assertEqual(result, 659486)
        call.assert_awaited_once_with({}, hint="_id_")

    def test_filtered_list_search_does_not_force_id_index(self):
        query = {"awardee_tax_id": "B12345678"}
        _, call = run_count(self.list_count(), query)
        call.assert_awaited_once_with(query)

    def test_compound_filter_is_preserved(self):
        query = {"$and": [{"amount": {"$gt": 0}}, {"cpv_code": "72000000"}]}
        _, call = run_count(self.list_count(), query)
        call.assert_awaited_once_with(query)


if __name__ == "__main__":
    unittest.main()
