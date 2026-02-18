# backend/soc/detections.py
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional


FAILED_RE = re.compile(
    r"Failed password for (?:(invalid user) )?(?P<user>\S+) from (?P<ip>\d+\.\d+\.\d+\.\d+)"
)


@dataclass
class SOCFinding:
    total_failed: int
    unique_ips: int
    top_ips: list[tuple[str, int]]
    top_users: list[tuple[str, int]]
    severity: str
    summary: str


def parse_failed_password(lines: list[str]) -> list[tuple[str, str]]:
    """
    Returns list of (ip, user) for 'Failed password' sshd style logs.
    """
    hits: list[tuple[str, str]] = []
    for line in lines:
        m = FAILED_RE.search(line)
        if not m:
            continue
        ip = m.group("ip")
        user = m.group("user")
        hits.append((ip, user))
    return hits


def classify_severity(total_failed: int, unique_ips: int, max_ip_count: int) -> str:
    # simple SOC-ish thresholds (tune later)
    if total_failed >= 30 or max_ip_count >= 20:
        return "HIGH"
    if total_failed >= 10 or max_ip_count >= 8:
        return "MED"
    if total_failed >= 5:
        return "LOW"
    return "INFO"


def detect_bruteforce(lines: list[str]) -> SOCFinding:
    hits = parse_failed_password(lines)

    ip_counts = Counter([ip for ip, _ in hits])
    user_counts = Counter([user for _, user in hits])

    total_failed = len(hits)
    unique_ips = len(ip_counts)
    max_ip_count = max(ip_counts.values()) if ip_counts else 0

    severity = classify_severity(total_failed, unique_ips, max_ip_count)

    top_ips = ip_counts.most_common(5)
    top_users = user_counts.most_common(5)

    if total_failed == 0:
        summary = "No failed-password events detected."
    else:
        top_ip = top_ips[0][0]
        summary = f"Detected {total_failed} failed logins from {unique_ips} IP(s). Top attacker IP: {top_ip}."

    return SOCFinding(
        total_failed=total_failed,
        unique_ips=unique_ips,
        top_ips=top_ips,
        top_users=top_users,
        severity=severity,
        summary=summary,
    )
