import urllib.request
import json
import logging
from config import SAT_SCHEDULE, get_current_date, get_next_score_release

logger = logging.getLogger(__name__)

CB_ALERTS_ENDPOINT = "https://athena.collegeboard.org/api/alerts-prod.json"
CB_SCORES_PAGE = "https://satsuite.collegeboard.org/scores/score-release-dates"


def fetch_collegeboard_alerts() -> list[dict]:
    """Fetches real-time alert feed from College Board."""
    try:
        req = urllib.request.Request(
            CB_ALERTS_ENDPOINT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug("Could not fetch College Board alerts feed: %s", e)
    return []


def detect_early_score_release() -> tuple[bool, str]:
    """
    Checks if College Board has posted an alert indicating scores are released early.
    Returns (is_released, details_text).
    """
    alerts = fetch_collegeboard_alerts()
    keywords = ["score", "scores", "released", "available", "score report"]

    for alert in alerts:
        header = alert.get("header", "").lower()
        body = alert.get("body", "") or alert.get("p", "") or ""
        combined = f"{header} {body}".lower()

        if any(k in combined for k in ["sat score", "scores are now available", "scores released", "view your score"]):
            logger.info("Early score release alert detected from College Board feed: %s", header)
            return True, alert.get("header", "Scores Released")

    return False, ""
