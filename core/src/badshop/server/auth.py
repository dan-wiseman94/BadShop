"""Actor-bound credentials: a CLI proxy never receives the renderer's user token."""
import hashlib
import hmac


def actor_token(user_token: str, actor: str) -> str:
    if actor == "user":
        return user_token
    return hmac.new(user_token.encode(), ("badshop.actor.v1:" + actor).encode(), hashlib.sha256).hexdigest()
