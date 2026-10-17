"""Small guards for the places user input reaches the file system or the network.

* ``safe_filename`` / ``inside``: a name or path from a request never leaves its folder.
* ``check_upload``: uploads are the type they claim (extension and magic bytes) and not
  too big.
* ``check_outbound_url``: server-side requests to user-supplied URLs (webhooks) do not
  reach loopback, private, link-local or cloud-metadata addresses, unless the host is a
  provider base URL the operator configured or is listed in ``server.fetch_allow_hosts``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from fastapi import HTTPException

from chatppt.settings import Settings, get_settings

# --------------------------------------------------------------------------- paths

_UNSAFE_NAME = re.compile(r"[^\w.\- ()+@]")


def safe_filename(name: str | None, default: str = "file") -> str:
    """The last path component of ``name``, with separators, control characters and
    leading dots removed; never empty, ``.`` or ``..``."""
    raw = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").split("/")[-1]
    cleaned = _UNSAFE_NAME.sub("_", raw).strip(" .")[:180]
    return cleaned or default


def inside(path: str | os.PathLike[str], roots: Iterable[str | os.PathLike[str]]) -> Path:
    """``path`` resolved (symlinks followed) if it lies inside one of ``roots``; otherwise a
    400. Use it on every path a request names."""
    target = Path(path).resolve()
    for root in roots:
        if target.is_relative_to(Path(root).resolve()):
            return target
    raise HTTPException(status_code=400, detail="Path is outside the allowed folders")


def upload_roots() -> list[str]:
    """Where uploaded documents live: the temp folder and ``<data>/uploads``."""
    from utils.get_env import get_app_data_directory_env, get_temp_directory_env

    roots = [get_temp_directory_env() or "/tmp/chatppt"]
    data = get_app_data_directory_env()
    if data:
        roots.append(os.path.join(data, "uploads"))
    return roots


# --------------------------------------------------------------------------- uploads


class _Upload(Protocol):
    filename: str | None
    size: int | None

    async def read(self, size: int = -1) -> bytes: ...

    async def seek(self, offset: int) -> None: ...


_IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
    ".bmp": (b"BM",),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
}
_FONT_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".ttf": (b"\x00\x01\x00\x00", b"true", b"OTTO"),
    ".otf": (b"OTTO", b"\x00\x01\x00\x00"),
    ".woff": (b"wOFF",),
    ".woff2": (b"wOF2",),
    ".eot": (),  # no fixed leading magic; size and extension only
}
KINDS: dict[str, tuple[dict[str, tuple[bytes, ...]], int]] = {
    "image": ({**_IMAGE_MAGIC, ".svg": ()}, 20),
    "font": (_FONT_MAGIC, 15),
}


async def check_upload(file: _Upload, kind: str) -> str:
    """Raise 400/413 unless ``file`` is an allowed ``kind`` (``image`` or ``font``) by
    extension and leading bytes, within its size cap (and ``server.max_upload_mb``).
    Returns the safe file name."""
    allowed, cap_mb = KINDS[kind]
    name = safe_filename(file.filename, default="")
    ext = os.path.splitext(name)[1].lower()
    if not name or ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported {kind} type. Allowed: {', '.join(sorted(allowed))}")
    cap = min(cap_mb, get_settings().server.max_upload_mb) * 1024 * 1024
    if file.size is not None and file.size > cap:
        raise HTTPException(status_code=413, detail=f"{kind.capitalize()} is larger than {cap // (1024 * 1024)} MB")
    head = await file.read(512)
    await file.seek(0)
    magic = allowed[ext]
    if ext == ".svg":
        if b"<svg" not in head.lower() and b"<?xml" not in head.lower():
            raise HTTPException(status_code=400, detail="File is not an SVG image")
    elif magic and not any(head.startswith(m) for m in magic):
        raise HTTPException(status_code=400, detail=f"File content does not match its {ext} extension")
    return name


# --------------------------------------------------------------------------- outbound URLs


def _configured_bases(settings: Settings) -> set[str]:
    """host:port of every provider base URL the operator set (toml or legacy env)."""
    urls: list[str | None] = []
    for creds in [*settings.llm.providers.values(), *settings.images.providers.values()]:
        urls += [creds.base_url, creds.endpoint]
    for name in (
        "OLLAMA_URL",
        "CUSTOM_LLM_URL",
        "LMSTUDIO_BASE_URL",
        "LITELLM_BASE_URL",
        "COMFYUI_URL",
        "OPEN_WEBUI_IMAGE_URL",
        "OPENAI_COMPAT_IMAGE_BASE_URL",
    ):
        urls.append(os.environ.get(name))
    return {_host_port(u) for u in urls if u}


def _host_port(url: str) -> str:
    parts = urlsplit(url if "://" in url else f"http://{url}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{(parts.hostname or '').lower()}:{port}"


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


async def check_outbound_url(url: str, settings: Settings | None = None) -> None:
    """Raise 400 unless ``url`` is http(s) and resolves only to public addresses (or its
    host is a configured provider / ``server.fetch_allow_hosts`` entry)."""
    settings = settings or get_settings()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HTTPException(status_code=400, detail="URL must be http(s) with a host")
    host_port = _host_port(url)
    allowed = {h.lower() for h in settings.server.fetch_allow_hosts}
    if host_port in _configured_bases(settings) or parts.hostname.lower() in allowed or host_port in allowed:
        return
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or 0, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"Cannot resolve {parts.hostname}") from exc
    for info in infos:
        if _blocked(ipaddress.ip_address(info[4][0])):
            raise HTTPException(
                status_code=400,
                detail=f"{parts.hostname} is a private or local address; add it to server.fetch_allow_hosts to allow it",
            )
