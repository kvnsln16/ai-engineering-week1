from app.connectors.tier2.tldr_ai import TldrAiConnector
from app.connectors.tier2.bens_bites import BensBitesConnector
from app.connectors.tier2.import_ai import ImportAiConnector
from app.connectors.tier2.last_week_in_ai import LastWeekInAiConnector
from app.connectors.tier2.latent_space import LatentSpaceConnector

TIER2_CONNECTORS = [
    TldrAiConnector(),
    BensBitesConnector(),
    ImportAiConnector(),
    LastWeekInAiConnector(),
    LatentSpaceConnector(),
]

__all__ = [
    "TIER2_CONNECTORS",
    "TldrAiConnector",
    "BensBitesConnector",
    "ImportAiConnector",
    "LastWeekInAiConnector",
    "LatentSpaceConnector",
]
