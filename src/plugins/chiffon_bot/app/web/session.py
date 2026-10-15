"""Process-local identities bound to editor links by authenticated private bot events."""
from __future__ import annotations

from dataclasses import dataclass, field
from secrets import token_urlsafe
from time import monotonic

from fastapi import HTTPException

SESSION_TTL = 3600


@dataclass
class Member:
    key: str = field(repr=False)
    user_id: int
    platform_id: str
    adapter: str
    label: str
    expires: float


class EditorSessions:
    # shortcut: sessions are process-local; use shared storage before adding bot workers.
    def __init__(self, *, superusers=lambda: (), clock=monotonic):
        self.superusers = superusers
        self.clock = clock
        self.members: dict[str, Member] = {}
        self.attempts: dict[str, tuple[float, int]] = {}

    def clear(self):
        self.members.clear()
        self.attempts.clear()

    def clean(self):
        now = self.clock()
        for key, item in list(self.members.items()):
            if item.expires <= now:
                self.members.pop(key, None)
        for key, (started, _) in list(self.attempts.items()):
            if now - started >= 60:
                self.attempts.pop(key, None)

    def limit(self, key):
        self.clean()
        started, count = self.attempts.get(key, (self.clock(), 0))
        if count >= 10 or (key not in self.attempts and len(self.attempts) >= 2048):
            raise HTTPException(429, "操作过于频繁，请一分钟后重试", headers={"Retry-After": "60"})
        self.attempts[key] = (started, count + 1)

    def issue(self, *, user_id, platform_id, adapter, label, ttl=SESSION_TTL):
        self.clean()
        if len(self.members) >= 512:
            raise HTTPException(503, "登录会话较多，请稍后重试")
        member = Member(token_urlsafe(32), user_id, platform_id, adapter, label,
                        self.clock() + min(ttl, SESSION_TTL))
        self.members[member.key] = member
        return member

    def member(self, key):
        self.clean()
        member = self.members.get(key or "")
        if not member:
            raise HTTPException(401, "登录已失效，请重新登录")
        return member

    def live(self, member):
        return self.members.get(member.key) is member and member.expires > self.clock()

    def admin(self, member):
        allowed = self.superusers()
        return self.live(member) and (member.platform_id in allowed
                                     or f"{member.adapter}:{member.platform_id}" in allowed)

    def policy(self, member, mine=False):
        def allowed(actor, action, game):
            return actor == member.user_id and self.live(member) and (
                action == "submit" or (not mine and self.admin(member)))
        return allowed
