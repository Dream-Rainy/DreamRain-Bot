"""Short lived identities issued only from authenticated bot events."""
from dataclasses import dataclass, field
from secrets import token_urlsafe
from time import monotonic

from fastapi import HTTPException

SESSION_TTL = 3600


@dataclass
class Identity:
    key: str = field(repr=False)
    platform_id: str
    adapter: str
    label: str
    expires: float
    bot_id: str = ""
    group_id: int | None = None
    cleanup: list = field(default_factory=list, repr=False)


class Sessions:
    member_type = Identity

    # shortcut: sessions are process-local; use shared storage before adding bot workers.
    def __init__(self, *, superusers=lambda: (), clock=monotonic):
        self.superusers, self.clock = superusers, clock
        self.members, self.attempts = {}, {}

    def revoke(self, key):
        member = self.members.pop(key, None)
        if member:
            for cleanup in member.cleanup:
                cleanup()

    def clear(self):
        for key in list(self.members):
            self.revoke(key)
        self.attempts.clear()

    def clean(self):
        now = self.clock()
        for key, member in list(self.members.items()):
            if member.expires <= now:
                self.revoke(key)
        for key, (started, _) in list(self.attempts.items()):
            if now - started >= 60:
                self.attempts.pop(key, None)

    def limit(self, key):
        self.clean()
        started, count = self.attempts.get(key, (self.clock(), 0))
        if count >= 10 or (key not in self.attempts and len(self.attempts) >= 2048):
            raise HTTPException(429, "操作过于频繁，请一分钟后重试", headers={"Retry-After": "60"})
        self.attempts[key] = started, count + 1

    def issue(self, *, ttl=SESSION_TTL, **identity):
        self.clean()
        if len(self.members) >= 512:
            raise HTTPException(503, "登录会话较多，请稍后重试")
        member = self.member_type(key=token_urlsafe(32), expires=self.clock() + min(ttl, SESSION_TTL), **identity)
        self.members[member.key] = member
        return member

    def member(self, key):
        self.clean()
        member = self.members.get(key or "")
        if not member:
            raise HTTPException(401, "登录已失效，请重新私聊机器人获取链接")
        return member

    def live(self, member):
        return self.members.get(member.key) is member and member.expires > self.clock()

    def admin(self, member):
        allowed = self.superusers()
        return self.live(member) and (member.platform_id in allowed or f"{member.adapter}:{member.platform_id}" in allowed)
