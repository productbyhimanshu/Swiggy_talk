"""Conservative ETA parsing — architecture §6.

Always use the worst-case (maximum) value from a range string.
'25-30 mins' → 30   (architecture: "always max from 25-30 mins")
'15 mins'    → 15
''           → 45   (default when unparseable)
"""

from __future__ import annotations

import re

_DEFAULT_ETA = 45  # minutes — used when string is unparseable


def parse_eta(delivery_time_str: str) -> int:
    """
    Parse a Swiggy deliveryTime string to an integer (worst-case minutes).

    Examples:
        '25-30 mins'  → 30
        '15 mins'     → 15
        '60-90 mins'  → 90
        ''            → 45
        'ASAP'        → 45
    """
    if not delivery_time_str:
        return _DEFAULT_ETA

    nums = [int(n) for n in re.findall(r"\d+", delivery_time_str)]
    if not nums:
        return _DEFAULT_ETA

    return max(nums)
