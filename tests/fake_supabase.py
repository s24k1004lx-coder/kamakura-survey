"""lib/db.py を本物のコードのままテストするための、最小限のインメモリ Supabase クライアント

PostgREST と同じく、update/delete は該当行がなくてもエラーにならず data=[] を返す。
responses.group_id / answers.response_id の外部キーは本番と同じくチェックする。
"""
import uuid
from datetime import datetime, timezone

FOREIGN_KEYS = {"responses": ("group_id", "survey_groups"),
                "answers": ("response_id", "responses")}


class APIError(Exception):
    pass


class _Result:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.payload, self.filters = db, table, "select", None, []
        self._count = None

    # --- 操作 ---
    def select(self, *_cols, count=None):
        self.op, self._count = "select", count
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, row):
        self.op, self.payload = "update", row
        return self

    def delete(self):
        self.op = "delete"
        return self

    # --- 絞り込み（テストで使うものだけ） ---
    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def is_(self, col, val):
        self.filters.append(lambda r: r.get(col) is None if val == "null" else r.get(col) == val)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def _match(self):
        return [r for r in self.db[self.table] if all(f(r) for f in self.filters)]

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.op == "insert":
            fk = FOREIGN_KEYS.get(self.table)
            if fk and not any(p["id"] == self.payload[fk[0]] for p in self.db.get(fk[1], [])):
                raise APIError(f"insert or update on table \"{self.table}\" violates foreign key constraint")
            row = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
                   "is_deleted": False, **self.payload}
            rows.append(row)
            return _Result([dict(row)])
        hit = self._match()
        if self.op == "update":
            for r in hit:
                r.update(self.payload)
            return _Result([dict(r) for r in hit])
        if self.op == "delete":
            for r in hit:
                rows.remove(r)
            return _Result([dict(r) for r in hit])
        return _Result([dict(r) for r in hit], count=len(hit) if self._count else None)


class FakeClient:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return _Query(self.db, name)
