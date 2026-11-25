"""TEST-ONLY design reference, NOT PostgreSQL, a production mock or implementation.

This model intentionally implements the PROPOSED rules. Its tests cannot establish
SQL atomicity, RLS, ACLs, persistence or real provider/browser authentication.
No existing OAuth tests or external-provider fakes use this model.
"""

import hashlib
import re
import threading
from uuid import UUID


class StorageFailure(RuntimeError):
    pass


def hashed(purpose, value):
    return hashlib.sha256(purpose.encode() + b"\0" + value.encode()).digest()


class StorageModel:
    def __init__(self):
        self.now = 1000
        self.available = True
        self.users = [
            dict(id=str(UUID(int=1)), email="password@example.invalid", provider="email",
                 password_hash="synthetic-hash", github_subject=None),
            dict(id=str(UUID(int=2)), email="legacy@example.invalid", provider="github",
                 password_hash=None, github_subject=None),
            dict(id=str(UUID(int=3)), email="bound@example.invalid", provider="github",
                 password_hash=None, github_subject="700"),
        ]
        self.attempts = {}
        self.handoffs = {}
        self.lock = threading.RLock()
        self.sequence = 100

    def guard(self, role):
        if role != "backend":
            raise PermissionError("Backend only (reference rule, not a real DB role)")
        if not self.available:
            raise StorageFailure("Synthetic storage unavailable")

    @staticmethod
    def valid_hash(value):
        return isinstance(value, bytes) and len(value) == 32

    def revoke_rows(self, binding):
        for row in [*self.attempts.values(), *self.handoffs.values()]:
            if row["binding"] == binding and row["revoked"] is None:
                row["revoked"] = self.now

    def start(self, state, binding, role="backend"):
        with self.lock:
            self.guard(role)
            if not all(map(self.valid_hash, (state, binding))):
                return False
            if state in self.attempts:
                raise StorageFailure("Synthetic unique state violation")
            self.revoke_rows(binding)
            self.attempts[state] = dict(binding=binding, provider="github", created=self.now,
                expires=self.now + 300, consumed=None, completed=None, revoked=None)
            return True

    def consume(self, state, binding, role="backend"):
        with self.lock:
            self.guard(role)
            if not all(map(self.valid_hash, (state, binding))):
                return False
            row = self.attempts.get(state)
            if not row or row["binding"] != binding or row["provider"] != "github" \
                    or row["expires"] <= self.now or row["consumed"] is not None \
                    or row["revoked"] is not None:
                return False
            row["consumed"] = self.now
            return True

    def finish(self, state, binding, ticket, subject, verified_email, role="backend"):
        with self.lock:
            self.guard(role)
            if not all(map(self.valid_hash, (state, binding, ticket))):
                return False
            if not isinstance(subject, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", subject) \
                    or not isinstance(verified_email, str) or not verified_email.strip():
                return False
            row = self.attempts.get(state)
            if not row or row["binding"] != binding or row["provider"] != "github" \
                    or row["consumed"] is None or row["completed"] is not None \
                    or row["revoked"] is not None or row["expires"] <= self.now:
                return False
            if ticket in self.handoffs:
                raise StorageFailure("Synthetic unique ticket violation")
            user = next((u for u in self.users if u["github_subject"] == subject), None)
            if user is None:
                if any(u["email"] == verified_email.lower() for u in self.users):
                    return False
                self.sequence += 1
                user = dict(id=str(UUID(int=self.sequence)), email=verified_email.lower(),
                    provider="github", password_hash=None, github_subject=subject)
                self.users.append(user)
            if not self.valid_user(user, subject):
                return False
            self.handoffs[ticket] = dict(state=state, binding=binding, user_id=user["id"],
                subject=subject, created=self.now, expires=min(self.now + 60, row["expires"]),
                consumed=None, revoked=None)
            row["completed"] = self.now
            return True

    @staticmethod
    def valid_user(user, subject):
        try:
            return isinstance(user["id"], str) and UUID(user["id"]).int != 0 \
                and user["github_subject"] == subject and user["provider"] == "github" \
                and user["password_hash"] is None
        except (ValueError, TypeError, KeyError):
            return False

    def redeem(self, ticket, binding, role="backend"):
        with self.lock:
            self.guard(role)
            if not all(map(self.valid_hash, (ticket, binding))):
                return None
            row = self.handoffs.get(ticket)
            if not row or row["binding"] != binding or row["expires"] <= self.now \
                    or row["consumed"] is not None or row["revoked"] is not None:
                return None
            attempt = self.attempts.get(row["state"])
            if not attempt or attempt["binding"] != binding or attempt["provider"] != "github" \
                    or attempt["consumed"] is None or attempt["completed"] is None \
                    or attempt["revoked"] is not None or attempt["expires"] <= self.now:
                return None
            user = next((u for u in self.users if u["id"] == row["user_id"]), None)
            if user is None or not self.valid_user(user, row["subject"]):
                return None
            row["consumed"] = self.now
            return user["id"], row["subject"]

    def revoke(self, binding, role="backend"):
        with self.lock:
            self.guard(role)
            if self.valid_hash(binding):
                self.revoke_rows(binding)

    def purge(self, role="backend"):
        with self.lock:
            self.guard(role)
            cutoff = self.now - 86400
            self.attempts = {k: v for k, v in self.attempts.items() if v["expires"] > cutoff}
            self.handoffs = {k: v for k, v in self.handoffs.items()
                             if v["expires"] > cutoff and v["state"] in self.attempts}
