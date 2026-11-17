
import asyncio
import calendar
import logging

from datetime import datetime, timezone, timedelta
from sqlalchemy import update

from ..database import SessionLocal
from .. import models
from .audit import record_change

logger = logging.getLogger(__name__)

# =========================================================
# CONFIG
# =========================================================

POLL_INTERVAL_S = 1
DEFAULT_DURATION_SECONDS = 10


# =========================================================
# TIME
# =========================================================

def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calculate_next_run(current_run_at, repeat_type):

    if repeat_type == "daily":
        return current_run_at + timedelta(days=1)

    if repeat_type == "weekly":
        return current_run_at + timedelta(weeks=1)

    if repeat_type == "monthly":

        year = current_run_at.year
        month = current_run_at.month

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

        last_day = calendar.monthrange(year, month)[1]
        day = min(current_run_at.day, last_day)

        return current_run_at.replace(
            year=year,
            month=month,
            day=day
        )

    return None


# =========================================================
# DATABASE OPERATIONS - SYNCHRONOUS
# =========================================================

def claim_event_sync(event_id: str):

    db = SessionLocal()

    try:
        now = utc_now_naive()

        # Atomically claim event.
        result = db.execute(
            update(models.ScheduledEvent)
            .where(
                models.ScheduledEvent.id == event_id,
                models.ScheduledEvent.status == "pending",
                models.ScheduledEvent.run_at <= now
            )
            .values(
                status="running",
                executed_at=None,
                error=None
            )
        )

        if result.rowcount != 1:
            db.commit()
            return None

        event = db.get(models.ScheduledEvent, event_id)

        if event is None:
            db.commit()
            return None

        record_change(
            db,
            event.created_by,
            "scheduled_event.start",
            f"scheduled_events:{event_id}",
            "running"
        )
        event_data = {
            "device_id": event.device_id,
            "command_name": event.command_name,
            "args": event.args,
            "current_run_at": event.run_at,
            "repeat_type": event.repeat_type,
            "duration_seconds": event.duration_seconds,
            "created_by": event.created_by
        }
        db.commit()
        return event_data

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def update_event_result_sync(
    event_id: str,
    event_data: dict,
    success: bool,
    error: str | None = None
):

    db = SessionLocal()

    try:
        event = db.get(models.ScheduledEvent, event_id)

        if event is None:
            return

        # Time when command finishes or fails.
        event.executed_at = utc_now_naive()

        if success:

            repeat_type = event_data["repeat_type"]

            if repeat_type == "once":

                event.status = "succeeded"
                event.error = None

            else:

                next_run = calculate_next_run(
                    event_data["current_run_at"],
                    repeat_type
                )

                if next_run is not None:

                    event.run_at = next_run
                    event.status = "pending"
                    event.error = None

                else:

                    event.status = "failed"
                    event.error = "Invalid repeat type"

        else:

            event.status = "failed"
            event.error = error or "Command failed"

        record_change(
            db,
            event_data.get("created_by"),
            "scheduled_event.complete",
            f"scheduled_events:{event_id}",
            event.status
        )
        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def get_due_events_sync():

    db = SessionLocal()

    try:
        events = db.query(
            models.ScheduledEvent.id
        ).filter(
            models.ScheduledEvent.status == "pending",
            models.ScheduledEvent.run_at <= utc_now_naive()
        ).all()

        return [event.id for event in events]

    finally:
        db.close()


# =========================================================
# ASYNC OPERATIONS
# =========================================================

async def execute_event(app, event_id: str):

    # 1. Claim event.
    event_data = await asyncio.to_thread(
        claim_event_sync,
        event_id
    )

    if event_data is None:
        return

    success = False
    error = None

    try:

        # 2. Determine command timeout.
        timeout = event_data["duration_seconds"]

        if timeout is None:
            timeout = DEFAULT_DURATION_SECONDS

        if timeout <= 0:
            raise ValueError(
                "duration_seconds must be greater than 0"
            )

        # 3. Send MQTT command and wait for result.
        await app.state.gateway.send_command(
            event_data["device_id"],
            event_data["command_name"],
            event_data["args"],
            timeout_s=timeout
        )



        success = True

    except asyncio.CancelledError:
        # Leave event as running.
        # Recovery is needed after cancellation/restart.
        raise

    except asyncio.TimeoutError:
        error = f"Command timeout after {timeout} seconds"

    except Exception as exc:
        error = str(exc) or type(exc).__name__

    # 4. Save result.
    await asyncio.to_thread(
        update_event_result_sync,
        event_id,
        event_data,
        success,
        error
    )


# =========================================================
# SCHEDULER LOOP
# =========================================================

async def scheduler_loop(app):

    logger.info("Scheduler started")

    while True:

        try:

            event_ids = await asyncio.to_thread(
                get_due_events_sync
            )

            for event_id in event_ids:

                try:

                    await execute_event(
                        app,
                        event_id
                    )

                except asyncio.CancelledError:
                    raise

                except Exception:
                    logger.exception(
                        "Scheduled event %s failed",
                        event_id
                    )

        except asyncio.CancelledError:
            logger.info("Scheduler stopped")
            raise

        except Exception:
            logger.exception("Scheduler loop error")

        await asyncio.sleep(POLL_INTERVAL_S)
