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
        "Selenium",
        "Tellurium",
        "Yttrium",
        "Polonium",
        "Ruthenium",
        "Technetium",
        "Arsenic",
        "Cadmium",
        "Niobium",
        "Vanadium",
        "Germanium",
        "Manganese",
        "Iron",
        "Nickel",
        "Carbon",
        "Sulphur",
        "Phosphorus",
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
    if search_type == "Mining":
        return MINING_RULES.get(item, {})

    return {}
