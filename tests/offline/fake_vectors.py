"""Raw in-memory Chroma surface: no completion or ownership enforcement.

Filtering follows the caller's actual predicate. Partial writes are injectable;
this models API shapes, not Chroma durability, transactions or concurrency.
"""
from copy import deepcopy


class MemoryCollection:
    def __init__(self):
        self.rows = {}
        self.write_limit = None
        self.add_error = None
        self.delete_error = None

    def count(self):
        return len(self.rows)

    @staticmethod
    def matches(metadata, where):
        if not where:
            return True
        if "$and" in where:
            return all(MemoryCollection.matches(metadata, term) for term in where["$and"])
        return all(metadata.get(key) in value["$in"] if isinstance(value, dict) and "$in" in value
                   else metadata.get(key) == value for key, value in where.items())

    def get(self, ids=None, where=None, include=None):
        selected = [(key, row) for key, row in self.rows.items()
                    if (ids is None or key in ids) and self.matches(row["metadata"], where)]
        result = {"ids": [key for key, _ in selected]}
        for field, item in (("documents", "document"), ("embeddings", "embedding"), ("metadatas", "metadata")):
            if include is None or field in include:
                result[field] = [deepcopy(row[item]) for _, row in selected]
        return result

    def add(self, ids, documents, embeddings, metadatas=None):
        for i, identifier in enumerate(ids):
            if self.write_limit is not None and i >= self.write_limit:
                break
            if identifier in self.rows:
                raise ValueError("synthetic duplicate ID")
            self.rows[identifier] = dict(document=documents[i], embedding=list(embeddings[i]),
                                         metadata=deepcopy(metadatas[i]) if metadatas else {})
        if self.add_error is not None:
            raise self.add_error

    def delete(self, ids):
        if self.delete_error is not None:
            raise self.delete_error
        for identifier in ids:
            self.rows.pop(identifier, None)

    def query(self, query_embeddings, n_results=5, where=None):
        # No semantic search simulation; deterministic raw rows only.
        rows = self.get(where=where)
        return {field: [rows[field][:n_results]]
                for field in ("ids", "documents", "metadatas")}
