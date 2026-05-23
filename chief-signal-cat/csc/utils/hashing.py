import hashlib


def stable_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]
