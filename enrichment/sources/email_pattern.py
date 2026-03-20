"""Constructed email pattern generator for UCSD faculty.

Generates candidate email addresses based on common UCSD naming patterns
and validates them via SMTP RCPT TO probe (does not send any mail).

This is a last-resort source — it runs only when no email has been found
from higher-confidence sources.  Generated emails are tagged with lower
confidence (0.5) so they can be distinguished from verified addresses.
"""

import logging
import re
import smtplib
import socket

from .base import BaseSource

logger = logging.getLogger(__name__)

# UCSD mail servers (MX records for ucsd.edu)
_UCSD_MX_HOSTS = [
    "ucsd-edu.mail.protection.outlook.com",
    "mx1.ucsd.edu",
]


def _generate_candidates(first_name, last_name):
    """Generate candidate email addresses from common UCSD patterns.

    Common patterns observed at UCSD:
    - flast@ucsd.edu          (first initial + last name)
    - first.last@ucsd.edu     (first.last)
    - filast@ucsd.edu         (first two initials + last)
    - firstl@ucsd.edu         (first name + last initial)
    - first@ucsd.edu          (first name only, rare)
    - last@ucsd.edu           (last name only, rare for common names)
    """
    first = first_name.lower().strip()
    last = last_name.lower().strip()

    if not first or not last:
        return []

    # Remove hyphens/spaces for pattern generation (e.g. "De Guzman" -> "deguzman")
    last_clean = re.sub(r"[\s\-']+", "", last)
    first_clean = re.sub(r"[\s\-']+", "", first)

    candidates = [
        f"{first_clean[0]}{last_clean}@ucsd.edu",        # flast
        f"{first_clean}.{last_clean}@ucsd.edu",           # first.last
        f"{first_clean[0:2]}{last_clean}@ucsd.edu",       # filast
        f"{first_clean}{last_clean[0]}@ucsd.edu",         # firstl
        f"{first_clean}{last_clean}@ucsd.edu",            # firstlast
        f"{last_clean}@ucsd.edu",                          # last (less common)
    ]

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _verify_smtp(email, timeout=10):
    """Verify an email address exists via SMTP RCPT TO.

    Connects to the UCSD MX server and issues RCPT TO to check whether
    the mailbox exists.  Does NOT send any mail.

    Returns True if the server accepts the recipient, False otherwise.
    Returns None if verification could not be performed (network error,
    server doesn't support RCPT verification, etc.).
    """
    for mx_host in _UCSD_MX_HOSTS:
        try:
            smtp = smtplib.SMTP(timeout=timeout)
            smtp.connect(mx_host, 25)
            smtp.helo("grantmatch.ucsd.edu")
            smtp.mail("probe@grantmatch.ucsd.edu")
            code, _ = smtp.rcpt(email)
            smtp.quit()
            if code == 250:
                return True
            if code in (550, 551, 553):
                return False
            # Other codes (e.g. 252 "cannot verify") are inconclusive
            return None
        except (smtplib.SMTPException, socket.error, OSError) as e:
            logger.debug("SMTP verification failed for %s via %s: %s", email, mx_host, e)
            continue

    return None  # Could not verify via any MX host


class EmailPatternSource(BaseSource):
    source_name = "email_pattern"
    min_request_interval = 0.5
    confidence = 0.5  # lower confidence — constructed, not observed

    def fields_provided(self):
        return ["email"]

    def fetch(self, faculty_dict):
        """Generate and optionally verify candidate email addresses."""
        first = faculty_dict.get("first_name", "")
        last = faculty_dict.get("last_name", "")

        # Skip if email already exists (higher-confidence sources ran first)
        if faculty_dict.get("email"):
            return None

        candidates = _generate_candidates(first, last)
        if not candidates:
            return None

        # Try SMTP verification for each candidate
        for candidate in candidates:
            result = _verify_smtp(candidate)
            if result is True:
                logger.info(
                    "SMTP-verified email %s for %s %s",
                    candidate, first, last,
                )
                return {"email": candidate}

        # If SMTP verification is unavailable (all returned None),
        # return the most likely pattern (first initial + last) without
        # verification, but flag it as unverified
        logger.info(
            "SMTP unavailable; returning best-guess email %s for %s %s",
            candidates[0], first, last,
        )
        return {
            "email": candidates[0],
            "_email_unverified": True,
        }
