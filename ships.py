from __future__ import annotations

from pathlib import Path
from typing import Optional


SHIP_INFO_MAP = {
    "sidewinder": ("Sidewinder", "sidewinder.png"),
    "eagle": ("Eagle", "eagle.png"),
    "hauler": ("Hauler", "hauler.png"),
    "adder": ("Adder", "adder.png"),

    "viper": ("Viper", "viper.png"),
    "viper_mkiv": ("Viper Mk IV", "viper_mkiv.png"),
    "cobra_mkiii": ("Cobra Mk III", "cobra_mkiii.png"),
    "cobra_mkiv": ("Cobra Mk IV", "cobra_mkiv.png"),

    "diamondback": ("Diamondback Scout", "diamondback.png"),
    "diamondbackxl": ("Diamondback Explorer", "diamondbackxl.png"),

    "type6": ("Type-6 Transporter", "type6.png"),
    "type7": ("Type-7 Transporter", "type7.png"),
    "type8": ("Type-8 Transporter", "type8.png"),
    "type9": ("Type-9 Heavy", "type9.png"),
    "type10": ("Type-10 Defender", "type10.png"),

    "dolphin": ("Dolphin", "dolphin.png"),
    "orca": ("Orca", "orca.png"),
    "belugaliner": ("Beluga Liner", "belugaliner.png"),

    "asp": ("Asp Scout", "asp.png"),
    "asp_scout": ("Asp Scout", "asp_scout.png"),
    "asp_explorer": ("Asp Explorer", "asp_explorer.png"),

    "vulture": ("Vulture", "vulture.png"),
    "mamba": ("Mamba", "mamba.png"),
    "ferdelance": ("Fer-de-Lance", "ferdelance.png"),

    "empire_courier": ("Imperial Courier", "empire_courier.png"),
    "cutter": ("Imperial Cutter", "cutter.png"),

    "federation_dropship": ("Federal Dropship", "federation_dropship.png"),
    "federation_corvette": ("Federal Corvette", "federation_corvette.png"),

    "alliance_chieftain": ("Alliance Chieftain", "alliance_chieftain.png"),
    "alliance_crusader": ("Alliance Crusader", "alliance_crusader.png"),
    "alliance_challenger": ("Alliance Challenger", "alliance_challenger.png"),

    "krait_mkii": ("Krait Mk II", "krait_mkii.png"),
    "krait_light": ("Krait Phantom", "krait_light.png"),

    "python": ("Python", "python.png"),
    "python_nx": ("Python Mk II", "python_nx.png"),

    "anaconda": ("Anaconda", "anaconda.png"),
    "panthermkii": ("Panther Clipper Mk II", "panthermkii.png"),
}


def friendly_ship_info(raw_name: Optional[str]) -> tuple[str, str]:
    if not raw_name:
        return ("Unknown ship", "unknown_ship.png")

    key = raw_name.strip().lower()
    return SHIP_INFO_MAP.get(key, (raw_name, "unknown_ship.png"))


def friendly_ship_name(raw_name: Optional[str]) -> str:
    return friendly_ship_info(raw_name)[0]


def friendly_ship_icon_path(raw_name: Optional[str]) -> Path:
    _, icon_file = friendly_ship_info(raw_name)
    return Path(__file__).resolve().parent / "assets" / "ships" / icon_file


def on_foot_icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "ships" / "on_foot.png"
