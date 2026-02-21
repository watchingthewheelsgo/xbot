"""
Analysis configuration - correlation topics, keywords, and patterns.
"""

import re
from dataclasses import dataclass


# Alert keywords for high-priority detection
ALERT_KEYWORDS: tuple[str, ...] = (
    "war",
    "invasion",
    "military",
    "nuclear",
    "sanctions",
    "missile",
    "attack",
    "troops",
    "conflict",
    "strike",
    "bomb",
    "casualties",
    "ceasefire",
    "treaty",
    "nato",
    "coup",
    "martial law",
    "emergency",
    "assassination",
    "terrorist",
    "hostage",
    "evacuation",
)

# Region keyword mapping
REGION_KEYWORDS: dict[str, list[str]] = {
    "EUROPE": [
        "nato",
        "eu",
        "european",
        "ukraine",
        "russia",
        "germany",
        "france",
        "uk",
        "britain",
        "poland",
    ],
    "MENA": [
        "iran",
        "israel",
        "saudi",
        "syria",
        "iraq",
        "gaza",
        "lebanon",
        "yemen",
        "houthi",
        "middle east",
    ],
    "APAC": [
        "china",
        "taiwan",
        "japan",
        "korea",
        "indo-pacific",
        "south china sea",
        "asean",
        "philippines",
    ],
    "AMERICAS": ["us", "america", "canada", "mexico", "brazil", "venezuela", "latin"],
    "AFRICA": ["africa", "sahel", "niger", "sudan", "ethiopia", "somalia"],
}

# Topic keyword mapping
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "CYBER": [
        "cyber",
        "hack",
        "ransomware",
        "malware",
        "breach",
        "apt",
        "vulnerability",
    ],
    "NUCLEAR": [
        "nuclear",
        "icbm",
        "warhead",
        "nonproliferation",
        "uranium",
        "plutonium",
    ],
    "CONFLICT": [
        "war",
        "military",
        "troops",
        "invasion",
        "strike",
        "missile",
        "combat",
        "offensive",
    ],
    "INTEL": ["intelligence", "espionage", "spy", "cia", "mossad", "fsb", "covert"],
    "DEFENSE": ["pentagon", "dod", "defense", "military", "army", "navy", "air force"],
    "DIPLO": [
        "diplomat",
        "embassy",
        "treaty",
        "sanctions",
        "talks",
        "summit",
        "bilateral",
    ],
}


@dataclass
class CorrelationTopic:
    """Topic definition with compiled regex patterns."""

    id: str
    patterns: list[re.Pattern]
    category: str


# Correlation topics with compiled regex patterns
CORRELATION_TOPICS: list[CorrelationTopic] = [
    CorrelationTopic(
        id="tariffs",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [r"tariff", r"trade war", r"import tax", r"customs duty"]
        ],
        category="Economy",
    ),
    CorrelationTopic(
        id="fed-rates",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"federal reserve",
                r"interest rate",
                r"rate cut",
                r"rate hike",
                r"powell",
                r"fomc",
            ]
        ],
        category="Economy",
    ),
    CorrelationTopic(
        id="inflation",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [r"inflation", r"\bcpi\b", r"consumer price", r"cost of living"]
        ],
        category="Economy",
    ),
    CorrelationTopic(
        id="ai-regulation",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"ai regulation",
                r"artificial intelligence.*law",
                r"ai safety",
                r"ai governance",
            ]
        ],
        category="Tech",
    ),
    CorrelationTopic(
        id="ai-breakthrough",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"gpt-?5",
                r"agi",
                r"artificial general",
                r"ai breakthrough",
                r"llm.*advance",
            ]
        ],
        category="Tech",
    ),
    CorrelationTopic(
        id="china-tensions",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"china.*taiwan",
                r"south china sea",
                r"us.*china",
                r"beijing.*washington",
            ]
        ],
        category="Geopolitics",
    ),
    CorrelationTopic(
        id="russia-ukraine",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"ukraine",
                r"zelensky",
                r"putin.*war",
                r"crimea",
                r"donbas",
                r"kyiv",
            ]
        ],
        category="Conflict",
    ),
    CorrelationTopic(
        id="israel-gaza",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"gaza",
                r"hamas",
                r"netanyahu",
                r"israel.*attack",
                r"hostage.*israel",
            ]
        ],
        category="Conflict",
    ),
    CorrelationTopic(
        id="iran",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"iran.*nuclear",
                r"tehran",
                r"ayatollah",
                r"iranian.*strike",
                r"irgc",
            ]
        ],
        category="Geopolitics",
    ),
    CorrelationTopic(
        id="north-korea",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"north korea",
                r"pyongyang",
                r"kim jong",
                r"dprk",
                r"korean.*missile",
            ]
        ],
        category="Geopolitics",
    ),
    CorrelationTopic(
        id="crypto",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"bitcoin",
                r"crypto.*regulation",
                r"ethereum",
                r"sec.*crypto",
                r"crypto.*crash",
            ]
        ],
        category="Finance",
    ),
    CorrelationTopic(
        id="housing",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"housing market",
                r"mortgage rate",
                r"home price",
                r"real estate.*crash",
            ]
        ],
        category="Economy",
    ),
    CorrelationTopic(
        id="layoffs",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"layoff",
                r"job cut",
                r"workforce reduction",
                r"downsizing",
                r"mass firing",
            ]
        ],
        category="Business",
    ),
    CorrelationTopic(
        id="bank-crisis",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"bank.*fail",
                r"banking crisis",
                r"fdic",
                r"bank run",
                r"bank.*collapse",
            ]
        ],
        category="Finance",
    ),
    CorrelationTopic(
        id="election",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"election",
                r"polling",
                r"campaign",
                r"ballot",
                r"voter",
                r"electoral",
            ]
        ],
        category="Politics",
    ),
    CorrelationTopic(
        id="immigration",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"immigration",
                r"border.*crisis",
                r"migrant",
                r"deportation",
                r"asylum",
            ]
        ],
        category="Politics",
    ),
    CorrelationTopic(
        id="climate",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"climate change",
                r"wildfire",
                r"hurricane",
                r"extreme weather",
                r"flood",
            ]
        ],
        category="Environment",
    ),
    CorrelationTopic(
        id="pandemic",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"pandemic",
                r"outbreak",
                r"virus.*spread",
                r"who.*emergency",
                r"bird flu",
                r"h5n1",
            ]
        ],
        category="Health",
    ),
    CorrelationTopic(
        id="nuclear-threat",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"nuclear.*threat",
                r"nuclear weapon",
                r"atomic",
                r"icbm",
                r"nuclear.*war",
            ]
        ],
        category="Security",
    ),
    CorrelationTopic(
        id="supply-chain",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"supply chain",
                r"shipping.*delay",
                r"port.*congestion",
                r"logistics.*crisis",
            ]
        ],
        category="Economy",
    ),
    CorrelationTopic(
        id="big-tech",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"antitrust.*tech",
                r"google.*monopoly",
                r"meta.*lawsuit",
                r"apple.*doj",
            ]
        ],
        category="Tech",
    ),
    CorrelationTopic(
        id="deepfake",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"deepfake",
                r"ai.*misinformation",
                r"synthetic media",
                r"ai.*fraud",
            ]
        ],
        category="Tech",
    ),
    CorrelationTopic(
        id="cybersecurity",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"cyber.*attack",
                r"ransomware",
                r"data breach",
                r"hack.*government",
                r"apt",
            ]
        ],
        category="Security",
    ),
    CorrelationTopic(
        id="oil-energy",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"oil price",
                r"opec",
                r"energy crisis",
                r"gas price",
                r"petroleum",
            ]
        ],
        category="Economy",
    ),
    CorrelationTopic(
        id="recession",
        patterns=[
            re.compile(p, re.IGNORECASE)
            for p in [
                r"recession",
                r"economic downturn",
                r"gdp.*decline",
                r"economic.*crisis",
            ]
        ],
        category="Economy",
    ),
]


def get_topic_by_id(topic_id: str) -> CorrelationTopic | None:
    """Get a topic by its ID."""
    for topic in CORRELATION_TOPICS:
        if topic.id == topic_id:
            return topic
    return None


def detect_region(text: str) -> str | None:
    """Detect region from text."""
    lower_text = text.lower()
    for region, keywords in REGION_KEYWORDS.items():
        if any(k in lower_text for k in keywords):
            return region
    return None


def detect_topics(text: str) -> list[str]:
    """Detect topics from text."""
    lower_text = text.lower()
    detected = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(k in lower_text for k in keywords):
            detected.append(topic)
    return detected


def contains_alert_keyword(text: str) -> tuple[bool, str | None]:
    """Check if text contains alert keywords."""
    lower_text = text.lower()
    for keyword in ALERT_KEYWORDS:
        if keyword in lower_text:
            return True, keyword
    return False, None
