"""Slack notification service."""

import logging

import aiohttp


def send_slack_notification(
    webhook_url: str,
    run_data: dict,
    artifact_repo: str,
    logger: logging.Logger | None = None,
) -> dict:
    """Send Slack notification with run summary.

    Args:
        webhook_url: Slack webhook URL
        run_data: Run results data
        artifact_repo: Artifact repository for report link
        logger: Logger instance

    Returns:
        Dictionary with success status
    """
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            _send_async(webhook_url, run_data, artifact_repo, logger)
        )
    finally:
        loop.close()

    return result


async def _send_async(
    webhook_url: str,
    run_data: dict,
    artifact_repo: str,
    logger: logging.Logger | None = None,
) -> dict:
    """Async implementation of Slack notification."""
    summary = run_data.get("summary", {})
    run_id = run_data.get("run_id", "unknown")
    run_date = run_data.get("started_at", "")[:10]

    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    pass_rate = (passed / total * 100) if total > 0 else 0

    # Calculate delta from previous run if available
    previous_pass_rate = summary.get("previous_pass_rate")
    delta_str = ""
    if previous_pass_rate is not None:
        delta = pass_rate - previous_pass_rate
        if delta > 0:
            delta_str = f" (+{delta:.1f}%)"
        elif delta < 0:
            delta_str = f" ({delta:.1f}%)"

    # Check for regressions
    regressions = run_data.get("regressions", [])
    has_regressions = len(regressions) > 0

    # Build message
    color = "#ef4444" if has_regressions else ("#10b981" if pass_rate >= 80 else "#f59e0b")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🔍 LocalStack Quality Monitor",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Run:* {run_id[:8]}"},
                {"type": "mrkdwn", "text": f"*Date:* {run_date}"},
                {"type": "mrkdwn", "text": f"*Pass Rate:* {pass_rate:.1f}%{delta_str}"},
                {"type": "mrkdwn", "text": f"*Architectures:* {total}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"✅ Passed: {passed}"},
                {"type": "mrkdwn", "text": f"❌ Failed: {failed}"},
            ],
        },
    ]

    # Add regression alert
    if has_regressions:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"⚠️ *{len(regressions)} REGRESSIONS DETECTED*",
            },
        })

    # Add report link
    report_url = f"https://github.com/{artifact_repo}/blob/main/reports/latest/index.html"
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"<{report_url}|View Full Report>",
        },
    })

    payload = {
        "attachments": [
            {
                "color": color,
                "blocks": blocks,
            }
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status == 200:
                    if logger:
                        logger.info("Slack notification sent successfully")
                    return {"success": True}
                else:
                    error = await response.text()
                    if logger:
                        logger.error(f"Slack notification failed: {error}")
                    return {"success": False, "error": error}

    except Exception as e:
        if logger:
            logger.error(f"Slack notification error: {e}")
        return {"success": False, "error": str(e)}
