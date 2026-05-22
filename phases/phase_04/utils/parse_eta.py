"""Phase 4 — conservative ETA parsing."""

import re


def parse_eta(delivery_time_str: str) -> int:
    nums = [int(n) for n in re.findall(r"\d+", delivery_time_str)]
    return max(nums) if nums else 45
