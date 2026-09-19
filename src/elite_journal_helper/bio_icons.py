from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import quote

from PyQt6.QtCore import QStandardPaths


# Small monochrome SVG silhouettes for the major Elite Dangerous
# exobiology genera. The current scan state controls the fill color.
_SVG_SHAPES: dict[str, str] = {
    "aleoida": """
        <path d="M12 21 L10 11 L6 18 L8 9 L3 15 L8 4 L12 12 L16 4 L15 13 L21 8 L16 18 L14 11 Z"/>
    """,
    "bacterium": """
        <ellipse cx="12" cy="12" rx="8" ry="5"/>
        <circle cx="8" cy="11" r="1.2" fill="#081018"/>
        <circle cx="13" cy="9.5" r="1.1" fill="#081018"/>
        <circle cx="16" cy="13" r="1.3" fill="#081018"/>
    """,
    "cactoida": """
        <path d="M10 21 V6 C10 3 14 3 14 6 V10 H17 V7 C17 5 20 5 20 7 V13 C20 15 18 16 14 16 V21 Z
                 M10 13 H7 V10 C7 8 4 8 4 10 V15 C4 17 6 18 10 18 Z"/>
    """,
    "clypeus": """
        <path d="M4 17 C5 9 8 5 12 5 C16 5 19 9 20 17 C17 15 15 14 12 14 C9 14 7 15 4 17 Z"/>
        <path d="M5 18 C8 15 10 14 12 14 C14 14 17 15 19 18 C16 20 8 20 5 18 Z"/>
        <path d="M12 6 V14" fill="none" stroke="#081018" stroke-width="1.5"/>
    """,
    "codonata": """
        <path d="M12 21 V12"/>
        <path d="M12 13 C5 12 4 7 8 4 C11 5 13 8 12 13 Z"/>
        <path d="M12 13 C19 12 20 7 16 4 C13 5 11 8 12 13 Z"/>
        <circle cx="12" cy="6" r="2.2"/>
    """,
    "concha": """
        <path d="M12 21
                 C9 18 4 15 4 10
                 C4 6 8 4 12 8
                 C16 4 20 6 20 10
                 C20 15 15 18 12 21 Z"/>
        <path d="M12 8 V5"
              fill="none"
              stroke="currentColor"
              stroke-width="2"/>
        <circle cx="12" cy="4" r="2.5"/>
        <path d="M12 1.5 V6.5 M9.5 4 H14.5 M10.2 2.2 L13.8 5.8 M13.8 2.2 L10.2 5.8"
              fill="none"
              stroke="currentColor"
              stroke-width="1"/>
    """,
    "electricae": """
        <path d="M13 2 L6 13 H11 L9 22 L18 10 H13 Z"/>
    """,
    "fonticulua": """
        <path d="M12 21 V11 M12 13 L6 8 M12 15 L18 9 M12 10 L9 5 M12 11 L15 4
                 M6 8 L4 5 M6 8 L3 10 M18 9 L21 6 M18 9 L21 11"
              fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
    """,
    "frutexa": """
        <path d="M12 21 V10 M12 12 L7 8 M12 14 L17 9 M7 8 L5 5 M7 8 L4 10
                 M17 9 L19 5 M17 9 L21 11" fill="none"
              stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
        <circle cx="5" cy="5" r="2"/><circle cx="19" cy="5" r="2"/>
        <circle cx="4" cy="10" r="2"/><circle cx="21" cy="11" r="2"/>
    """,
    "fungoida": """
        <path d="M6 21 V8 M12 21 V5 M18 21 V10"
              fill="none"
              stroke="currentColor"
              stroke-width="2.5"
              stroke-linecap="round"/>
        <circle cx="6" cy="7" r="2.5"/>
        <circle cx="12" cy="4" r="2.5"/>
        <circle cx="18" cy="9" r="2.5"/>
    """,
    "osseus": """
        <path d="M12 21 V5 M12 9 L7 6 M12 12 L17 8 M12 15 L7 13
                 M12 18 L17 15" fill="none"
              stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
    """,
    "recepta": """
        <path d="M5 5 H19 L16 13 H8 Z"/>
        <path d="M10 13 V20 H14 V13 Z"/>
        <circle cx="12" cy="7" r="2" fill="#081018"/>
    """,
    "stratum": """
        <!-- Low rocky outcrop -->
        <path d="
            M2 19
            C4 16 5 13 8 12
            C10 8 14 7 16 11
            C19 12 21 15 22 19
            Z
        "/>
    
        <!-- Uneven ridge line -->
        <path d="
            M3 18
            C5 16 6 14 8 14
            C10 11 12 10 14 11
            C16 10 18 12 20 16
        "
        fill="none"
        stroke="#081018"
        stroke-width="1.4"
        stroke-linecap="round"/>
    
        <!-- Surface grooves -->
        <path d="
            M6 17 C8 15 9 14 11 13
            M10 18 C12 16 14 15 16 14
            M15 18 C17 16 18 16 20 17
        "
        fill="none"
        stroke="#081018"
        stroke-width="1.1"
        stroke-linecap="round"/>
    """,
    "tubus": """
        <rect x="4" y="8" width="4" height="12" rx="2"/>
        <rect x="10" y="4" width="4" height="16" rx="2"/>
        <rect x="16" y="7" width="4" height="13" rx="2"/>
        <ellipse cx="6" cy="8" rx="2" ry="1" fill="#081018"/>
        <ellipse cx="12" cy="4" rx="2" ry="1" fill="#081018"/>
        <ellipse cx="18" cy="7" rx="2" ry="1" fill="#081018"/>
    """,
    "tussock": """
        <!-- Dense rounded grass mound -->
        <path d="
            M3 20
            C4 15 6 12 9 11
            C10 9 14 9 15 11
            C18 12 20 15 21 20
            Z
        "/>
    
        <!-- Hanging grass strands -->
        <path d="
            M6 14 L4 21
            M8 13 L7 22
            M10 12 L10 22
            M12 12 L12 22
            M14 12 L14 22
            M16 13 L17 22
            M18 14 L20 21
        "
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"/>
    
        <!-- Main flower spike -->
        <path d="
            M12 12
            C11 9 11 5 13 2
            C16 5 16 9 14 12
            Z
        "/>
    
        <!-- Texture dots on the spike -->
        <circle cx="13" cy="4" r="0.8" fill="#081018"/>
        <circle cx="14" cy="6" r="0.8" fill="#081018"/>
        <circle cx="13" cy="8" r="0.8" fill="#081018"/>
        <circle cx="14" cy="10" r="0.8" fill="#081018"/>
    """,
}

_GENERIC_SHAPE = """
    <circle cx="12" cy="12" r="8"/>
    <path d="M8 12 H16 M12 8 V16" fill="none" stroke="#081018" stroke-width="2"/>
"""


def genus_key(name: str) -> str:
    lowered = (name or "").lower()
    for genus in _SVG_SHAPES:
        if genus in lowered:
            return genus
    return "generic"


def _cache_dir() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )
    path = Path(base or Path.home() / ".cache") / "bio-icons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bio_icon_path(name: str, color: str, size: int = 16) -> Path:
    genus = genus_key(name)
    shape = _SVG_SHAPES.get(genus, _GENERIC_SHAPE)
    safe_color = color if color.startswith("#") else "#707780"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
        width="{size}" height="{size}" viewBox="0 0 24 24">
        <g color="{safe_color}" fill="{safe_color}">
            {shape}
        </g>
    </svg>"""

    digest = hashlib.sha1(
        f"{genus}|{safe_color}|{size}|{svg}".encode("utf-8")
    ).hexdigest()[:16]
    path = _cache_dir() / f"{genus}-{digest}.svg"

    if not path.exists():
        path.write_text(svg, encoding="utf-8")

    return path


def bio_icon_html(name: str, color: str, size: int = 16) -> str:
    path = bio_icon_path(name, color, size)
    tooltip = quote(name or "Unknown biological type")
    return (
        f"<img src='{path.as_uri()}' width='{size}' height='{size}' "
        f"title='{tooltip}'/>"
    )
