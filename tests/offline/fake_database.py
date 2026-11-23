"""Tiny PostgREST-shaped store: evaluates query predicates, never an actor/RLS.

Only the query subset exercised here is modeled. This is deliberately not a
Postgres/schema emulator: no foreign keys, UUID coercion, grants, or RLS. Invalid
principal tests require rejection BEFORE execute, independent of SQL behavior.
"""

from copy import deepcopy
from types import SimpleNamespace


USER_A = "00000000-0000-0000-0000-000000000001"
USER_B = "00000000-0000-0000-0000-000000000002"
SESSION_A = "00000000-0000-0000-0000-000000000011"
SESSION_B = "00000000-0000-0000-0000-000000000012"
ORPHAN = "00000000-0000-0000-0000-000000000013"


class DatabaseFailure(RuntimeError):
    pass


class MemoryDatabase:
    def __init__(self):
        self.rows = {
            "users": [
                {"id": USER_A, "email": "a@example.invalid", "provider": "email",
                 "password_hash": "synthetic-hash"},
                {"id": USER_B, "email": "b@example.invalid", "provider": "github",
                 "password_hash": None},
            ],
            "sessions": [
                self.session(SESSION_B, USER_B, "B"),
                self.session(SESSION_A, USER_A, "A"),
                self.session(ORPHAN, None, "orphan"),
            ],
        }
        self.calls = []
        self.errors = {}
        self.after_select = None
        self.sequence = 100

    @staticmethod
    def session(record_id, user_id, label):
        return {"id": record_id, "user_id": user_id, "filename": f"synthetic-{label}.txt",
                "pdf_text": f"synthetic source {label}", "notes": f"synthetic notes {label}",
                "chat_history": [], "timestamp": "2026-01-01T00:00:00+00:00"}

    def table(self, name):
        if name not in self.rows:
            raise AssertionError(f"Unsupported fake table: {name}")
        return Query(self, name)

    def row(self, table, record_id):
        return next((row for row in self.rows[table] if row.get("id") == record_id), None)


class Query:
    def __init__(self, database, table):
        self.database, self.name = database, table
        self.operation = None
        self.filters = []
        self.payload = None
        self.columns = "*"
        self.sort = None

    def select(self, columns):
        self.operation, self.columns = "select", columns
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", deepcopy(payload)
        return self

    def update(self, payload):
        self.operation, self.payload = "update", deepcopy(payload)
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, desc=False):
        self.sort = (column, desc)
        return self

    def execute(self):
        database = self.database
        database.calls.append({"table": self.name, "operation": self.operation,
                               "filters": deepcopy(self.filters), "payload": deepcopy(self.payload)})
        error = database.errors.get((self.name, self.operation))
        if error is not None:
            raise error
        rows = database.rows[self.name]
        # Equality with NULL does not fabricate ownership for orphan rows.
        matched = [row for row in rows if all(
            value is not None and row.get(column) == value for column, value in self.filters)]
        if self.operation == "insert":
            database.sequence += 1
            record = {"id": f"00000000-0000-0000-0000-{database.sequence:012d}", **self.payload}
            rows.append(record)
            return SimpleNamespace(data=[deepcopy(record)])
        if self.operation == "update":
            for row in matched:
                row.update(deepcopy(self.payload))
        elif self.operation == "delete":
            database.rows[self.name] = [row for row in rows if row not in matched]
        elif self.operation != "select":
            raise AssertionError(f"Unsupported fake operation: {self.operation}")
        result = deepcopy(matched)
        if self.sort:
            column, desc = self.sort
            result.sort(key=lambda row: row[column], reverse=desc)
        if self.columns != "*":
            result = [{key: row[key] for key in self.columns.split(",")} for row in result]
        if self.operation == "select" and database.after_select:
            database.after_select(self.name)
        return SimpleNamespace(data=result)
