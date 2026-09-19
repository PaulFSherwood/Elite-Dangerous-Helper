SEARCH_TYPES = {
    "None": [],
    "Mining": [
        "Tritium",
        "Low Temperature Diamonds",
        "Void Opals",
        "Painite",
        "Platinum",
        "Osmium",
        "Bromellite",
        "Alexandrite",
        "Benitoite",
        "Monazite",
        "Musgravite",
        "Serendibite",
        "Rhodplumsite",
        "Grandidierite",
    ],
    "Engineering": [
        "Carbon",
        "Sulphur",
        "Phosphorus",
        "Iron",
        "Nickel",
        "Chromium",
        "Manganese",
        "Germanium",
        "Vanadium",
        "Selenium",
        "Zinc",
        "Zirconium",
        "Arsenic",
        "Cadmium",
        "Mercury",
        "Niobium",
        "Tin",
        "Molybdenum",
        "Antimony",
        "Tungsten",
        "Tellurium",
        "Ruthenium",
        "Yttrium",
        "Polonium",
        "Technetium",
    ],
}


MINING_RULES = {
    "Tritium": {
        "conditions": ["Icy ring", "Gas giant preferred"],
        "match": "Icy ring; stronger match if parent is gas giant",
    },
    "Low Temperature Diamonds": {
        "conditions": ["Icy ring"],
        "match": "Icy ring",
    },
    "Void Opals": {
        "conditions": ["Icy ring"],
        "match": "Icy ring",
    },
    "Painite": {
        "conditions": ["Metallic ring", "Metal-rich ring possible"],
        "match": "Metallic or metal-rich ring",
    },
    "Platinum": {
        "conditions": ["Metallic ring"],
        "match": "Metallic ring",
    },
    "Osmium": {
        "conditions": ["Metallic ring", "Metal-rich ring"],
        "match": "Metallic or metal-rich ring",
    },
    "Bromellite": {
        "conditions": ["Icy ring"],
        "match": "Icy ring",
    },
    "Alexandrite": {
        "conditions": ["Icy ring"],
        "match": "Icy ring",
    },
    "Benitoite": {
        "conditions": ["Rocky ring", "Metal-rich ring possible"],
        "match": "Rocky or metal-rich ring",
    },
    "Monazite": {
        "conditions": ["Metallic ring", "Metal-rich ring"],
        "match": "Metallic or metal-rich ring",
    },
    "Musgravite": {
        "conditions": ["Rocky ring"],
        "match": "Rocky ring",
    },
    "Serendibite": {
        "conditions": ["Rocky ring"],
        "match": "Rocky ring",
    },
    "Rhodplumsite": {
        "conditions": ["Metallic ring"],
        "match": "Metallic ring",
    },
    "Grandidierite": {
        "conditions": ["Icy ring"],
        "match": "Icy ring",
    },
}


def get_items_for_type(search_type: str) -> list[str]:
    return SEARCH_TYPES.get(search_type, [])

def get_rule_description(search_type: str, item: str) -> dict:
    if search_type == "None" or item == "None":
        return {
            "conditions": [],
            "match": "No search target selected",
        }

    if search_type == "Mining":
        return MINING_RULES.get(item, {})

    if search_type == "Engineering":
        return {
            "conditions": [
                "Landable body",
                f"{item} present",
            ],
            "match": f"Body material list contains {item}",
        }

    return {}

def ring_class_matches(ring_class: str, wanted: str) -> bool:
    ring_class_lower = (ring_class or "").lower()
    wanted_lower = wanted.lower()

    if wanted_lower == "icy":
        return "icy" in ring_class_lower

    if wanted_lower == "metallic":
        return "metallic" in ring_class_lower

    if wanted_lower == "metal-rich":
        return "metalrich" in ring_class_lower or "metal-rich" in ring_class_lower

    if wanted_lower == "rocky":
        return "rocky" in ring_class_lower

    return False


def body_has_ring_type(body, ring_type: str) -> bool:
    for ring in getattr(body, "rings", []):
        if ring_class_matches(ring.get("RingClass", ""), ring_type):
            return True

    return False


def body_has_mining_signal(body, item_name: str) -> tuple[bool, int]:
    wanted = item_name.lower().replace(" ", "")

    aliases = {
        "lowtemperaturediamonds": ["lowtemperaturediamond", "lowtemp.diamonds", "lowtempdiamonds"],
        "voidopals": ["opal", "voidopal", "voidopals"],
        "tritium": ["tritium"],
        "alexandrite": ["alexandrite"],
        "painite": ["painite"],
        "platinum": ["platinum"],
        "osmium": ["osmium"],
        "bromellite": ["bromellite"],
    }

    wanted_terms = aliases.get(wanted, [wanted])

    for signal in getattr(body, "mining_signals", []):
        signal_type = str(signal.get("type", "")).lower().replace(" ", "")
        signal_local = str(signal.get("localised", "")).lower().replace(" ", "")

        if any(term in signal_type or term in signal_local for term in wanted_terms):
            return True, int(signal.get("count", 0))

    return False, 0

def material_key(name: str) -> str:
    return name.lower().replace(" ", "")

def body_has_engineering_material(body, material_name: str) -> tuple[bool, float]:
    wanted = material_key(material_name)

    for mat_name, percent in getattr(body, "materials", {}).items():
        if material_key(mat_name) == wanted:
            return True, float(percent)

    return False, 0.0

def evaluate_search_target(search_type: str, search_item: str, body) -> dict:
    if search_type == "Engineering" and search_item != "None":
        landable = getattr(body, "landable", False) is True
        found, percent = body_has_engineering_material(body, search_item)

        conditions = [
            ("Landable body", landable),
            (f"{search_item} present", found),
        ]

        if found:
            return {
                "title_confirmed": True,
                "conditions": conditions,
                "match_text": f"{search_item}: {percent:.1f}%",
            }

        return {
            "title_confirmed": False,
            "conditions": conditions,
            "match_text": "",
        }
    if search_type != "Mining" or search_item == "None":
        return {
            "title_confirmed": False,
            "conditions": [],
            "match_text": "",
        }

    subtype = (getattr(body, "subtype", "") or "").lower()

    is_gas_giant = "gas giant" in subtype
    has_icy_ring = body_has_ring_type(body, "icy")
    has_metallic_ring = body_has_ring_type(body, "metallic")
    has_metal_rich_ring = body_has_ring_type(body, "metal-rich")
    has_rocky_ring = body_has_ring_type(body, "rocky")

    confirmed, count = body_has_mining_signal(body, search_item)

    if search_item == "Tritium":
        conditions = [
            ("Gas giant", is_gas_giant),
            ("Icy ring", has_icy_ring),
        ]

        if confirmed:
            return {
                "title_confirmed": True,
                "conditions": conditions,
                "match_text": f"Confirmed Tritium hotspot x{count}",
            }

        if is_gas_giant and has_icy_ring:
            return {
                "title_confirmed": False,
                "conditions": conditions,
                "match_text": "Possible Tritium prospect: scan icy ring",
            }

        return {
            "title_confirmed": False,
            "conditions": conditions,
            "match_text": "",
        }

    if search_item in ("Low Temperature Diamonds", "Void Opals", "Bromellite", "Alexandrite", "Grandidierite"):
        conditions = [("Icy ring", has_icy_ring)]

    elif search_item in ("Painite", "Platinum", "Osmium", "Monazite", "Rhodplumsite"):
        conditions = [
            ("Metallic ring", has_metallic_ring),
            ("Metal-rich ring", has_metal_rich_ring),
        ]

    elif search_item in ("Benitoite", "Musgravite", "Serendibite"):
        conditions = [("Rocky ring", has_rocky_ring)]

    else:
        conditions = []

    if confirmed:
        return {
            "title_confirmed": True,
            "conditions": conditions,
            "match_text": f"Confirmed {search_item} hotspot x{count}",
        }

    if any(found for _, found in conditions):
        return {
            "title_confirmed": False,
            "conditions": conditions,
            "match_text": f"Possible {search_item} prospect",
        }

    return {
        "title_confirmed": False,
        "conditions": conditions,
        "match_text": "",
    }
