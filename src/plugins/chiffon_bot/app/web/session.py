"""Alias identities add a business id to shared sessions."""
from dataclasses import dataclass
from nonebot import require
require("src.plugins.management")
from src.plugins.management.session import Identity, Sessions, SESSION_TTL

@dataclass
class Member(Identity):
    user_id: int = 0

class EditorSessions(Sessions):
    member_type = Member

    def policy(self, member, mine=False):
        def allowed(actor, action, game):
            return actor == member.user_id and self.live(member) and (
                action == "submit" or (not mine and self.admin(member)))
        return allowed
