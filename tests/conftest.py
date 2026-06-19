import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import app


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, table, op, payload=None):
        self.table = table
        self.op = op  # 'select' | 'upsert' | 'delete'
        self.payload = payload
        self.filters = []

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self.filters.append(("neq", col, val))
        return self

    def _matches(self, row):
        for kind, col, val in self.filters:
            if kind == "eq" and row.get(col) != val:
                return False
            if kind == "neq" and row.get(col) == val:
                return False
        return True

    def execute(self):
        rows = self.table.rows
        if self.op == "select":
            return _Resp([r for r in rows if self._matches(r)])
        if self.op == "insert":
            rows.append(dict(self.payload))
            return _Resp([self.payload])
        if self.op == "upsert":
            pk = self.table.pk
            existing = next((r for r in rows if r.get(pk) == self.payload.get(pk)), None)
            if existing is not None:
                existing.update(self.payload)
            else:
                rows.append(dict(self.payload))
            return _Resp([self.payload])
        if self.op == "delete":
            removed = [r for r in rows if self._matches(r)]
            self.table.rows[:] = [r for r in rows if not self._matches(r)]
            return _Resp(removed)
        raise NotImplementedError(self.op)


class _FakeTable:
    def __init__(self, name):
        self.name = name
        self.rows = []
        self.pk = "usn" if name == "submissions" else "key"

    def select(self, cols="*"):
        return _FakeQuery(self, "select")

    def insert(self, payload):
        return _FakeQuery(self, "insert", payload)

    def upsert(self, payload):
        return _FakeQuery(self, "upsert", payload)

    def delete(self):
        return _FakeQuery(self, "delete")


class FakeSupabase:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return self.tables.setdefault(name, _FakeTable(name))


@pytest.fixture
def fake_supabase(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(app, "get_supabase", lambda: fake)
    return fake
