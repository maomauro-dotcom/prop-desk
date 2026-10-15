"""propdesk: paper trading desk for CME micro index futures (MNQ/MES). Live routing is disabled."""

import logging

logging.getLogger("propdesk").addHandler(logging.NullHandler())

__version__ = "0.1.0"
