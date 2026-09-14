
import threading
import copy
from typing import Optional
from pathlib import Path

try:
    from connection_manager import fingerprint, read_secret_source, resolve_secret_file
except ImportError:
    import hashlib
    def fingerprint(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()
    def read_secret_source(*a, **k):
        raise NotImplementedError()
    def resolve_secret_file(*a, **k):
        raise NotImplementedError()

_active_pool = {}
_pool_lock = threading.RLock()

def _build_candidate(source_path=None, provider=None, prefix=None):
    labeled = {}
    try:
        if source_path is not None and provider is not None and prefix is not None:
            labeled, _ = read_secret_source(source_path, prefix)
        elif provider and not source_path:
            path = resolve_secret_file(provider)
            from connection_manager import PROVIDER_PREFIXES
            pfx = PROVIDER_PREFIXES.get(provider.lower(), provider[:3].upper())
            labeled, _ = read_secret_source(path, pfx)
        else:
            return None, "invalid source arguments"
        if provider is not None and not labeled:
            return None, "no credentials found for provider"
        return labeled, None
    except Exception as e:
        return None, f"read error: {type(e).__name__}"

def _validate_candidate(candidate):
    for k, v in candidate.items():
        if not isinstance(v, dict) or "key_fingerprint" not in v or "status" not in v:
            return False, "incomplete entry"
        for val in v.values():
            if isinstance(val, str) and ("sk-" in val or val.startswith("Bearer ") or val.startswith("sk-")):
                return False, "secret exposure detected"
    return True, None


_reload_sequence = 0
_swap_lock = threading.Lock()

def reload_credential_pool(

    *,
    source_path: Optional[Path] = None,
    provider: Optional[str] = None,
    prefix: Optional[str] = None,
) -> dict:
    global _reload_sequence
    with _swap_lock:
        seq = _reload_sequence
        _reload_sequence += 1
    labeled, err = _build_candidate(source_path=source_path, provider=provider, prefix=prefix)
    if err:
        with _pool_lock:
            previous = copy.deepcopy(dict(_active_pool))
        return {"status": "failure", "reason": err, "previous_pool_keys": sorted(previous)}
    candidate_pool = {}
    for cid, secret in labeled.items():
        fp = fingerprint(secret)
        candidate_pool[cid] = {"key_fingerprint": fp, "status": "discovered"}
    ok, reason = _validate_candidate(candidate_pool)
    with _pool_lock:
        previous = copy.deepcopy(dict(_active_pool))
        if not ok:
            return {"status": "failure", "reason": reason, "previous_pool_keys": sorted(previous)}
        _active_pool.clear()
        for k, v in candidate_pool.items():
            _active_pool[k] = dict(v)
        reload_credential_pool._last_swapped_seq = seq
        return {"status": "success", "pool_keys": sorted(candidate_pool), "previous_pool_keys": sorted(previous)}

def get_active_pool() -> dict:
    with _pool_lock:
        return copy.deepcopy(dict(_active_pool))

def get_pool_health() -> dict:
    with _pool_lock:
        return copy.deepcopy({k: {"fingerprint": v.get("key_fingerprint"), "status": v.get("status")} for k, v in _active_pool.items()})
