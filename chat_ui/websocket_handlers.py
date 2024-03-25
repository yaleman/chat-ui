from datetime import datetime, UTC, timedelta
import json
import traceback
from typing import Optional
from uuid import UUID
from fastapi import WebSocket
from loguru import logger

from pydantic import BaseModel
from sqlmodel import Session, or_, select

from sqlalchemy.exc import NoResultFound
from chat_ui.db import JobFeedback, Jobs

from chat_ui.models import (
    Job,
    JobStatus,
    LogMessages,
    WebSocketMessage,
    WebSocketMessageType,
    WebSocketResponse,
    validate_uuid,
)
from chat_ui.utils import get_client_ip, get_waiting_jobs


async def websocket_resubmit(
    data: WebSocketMessage,
    session: Session,
    websocket: WebSocket,
) -> WebSocketResponse:
    try:

        query = select(Jobs).where(Jobs.id == data.payload, Jobs.userid == data.userid)
        res = session.exec(query).one()
        # only accept the resubmit if it was an error
        if res.status == JobStatus.Error.value:
            res.status = JobStatus.Created.value
            res.response = ""
            res.updated = datetime.now(UTC)
            session.add(res)
            session.commit()
            session.refresh(res)
            logger.debug(
                LogMessages.Resubmitted,
                src_ip=get_client_ip(websocket),
                **data.model_dump(),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Resubmit.value,
                payload=res.model_dump_json(),
            )
        else:
            logger.debug(
                LogMessages.RejectedResubmit,
                status=res.status,
                src_ip=get_client_ip(websocket),
                **data.model_dump(),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Error.value,
                payload=f"Job {data.payload} is not in an error state",
            )
    except NoResultFound:
        logger.debug(
            LogMessages.NoJobs, src_ip=get_client_ip(websocket), **data.model_dump()
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload=f"No job ID found matching {data.payload}",
        )
    except Exception as error:
        logger.error(
            LogMessages.ResubmitFailed,
            error=error,
            src_ip=get_client_ip(websocket),
            **data.model_dump(),
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload=f"Error handling {data.payload}",
        )
    return response


async def websocket_waiting(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    """work out how many jobs are waiting"""

    try:
        # don't want to hit the DB too often...
        (last_update, waiting) = get_waiting_jobs(session)

        if last_update < datetime.now(UTC) - timedelta(seconds=5):
            get_waiting_jobs.cache_clear()
            (last_update, waiting) = get_waiting_jobs(session)

        response = WebSocketResponse(
            message=WebSocketMessageType.Waiting.value,
            payload=json.dumps(waiting, default=str),
        )

    except Exception as error:
        logger.error(
            LogMessages.WebsocketError,
            error=error,
            src_ip=get_client_ip(websocket),
            **data.model_dump(),
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="Failed to get count of pending jobs...",
        )
    return response


async def websocket_feedback(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    """handle a user's feedback response"""
    if data.payload is None:
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="No payload specified when sending feedback!",
        )
        return response
    try:
        feedback = JobFeedback(
            **json.loads(data.payload or ""), src_ip=get_client_ip(websocket)
        )
    except Exception as error:
        logger.error(
            LogMessages.WebsocketError,
            src_ip=get_client_ip(websocket),
            error=str(error),
            **data.model_dump(),
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="Exception handling feedback, please try again!",
        )
        return response

    try:
        if JobFeedback.has_feedback(session, feedback.jobid):
            try:
                query = select(JobFeedback).where(JobFeedback.jobid == feedback.jobid)
                existing_feedback = session.exec(query).one()
                for field in existing_feedback.model_fields:
                    if field in feedback.model_fields:
                        setattr(existing_feedback, field, getattr(feedback, field))
                existing_feedback.created = datetime.now(UTC)
                session.add(existing_feedback)
                session.commit()
                session.refresh(existing_feedback)
                response = WebSocketResponse(
                    message=WebSocketMessageType.Feedback.value, payload="OK"
                )
                logger.debug(
                    LogMessages.JobFeedback,
                    **existing_feedback.model_dump(warnings=False, round_trip=True),
                )
            except NoResultFound:
                logger.error(
                    LogMessages.NoJobs.value,
                    src_ip=get_client_ip(websocket),
                    **feedback.model_dump(),
                )
                response = WebSocketResponse(
                    message=WebSocketMessageType.Error.value,
                    payload="No job!",
                )

        else:
            session.add(feedback)
            session.commit()
            session.refresh(feedback)
            logger.info(
                LogMessages.JobFeedback,
                **feedback.model_dump(warnings=False, round_trip=True),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Feedback.value, payload="OK"
            )
    except Exception:
        logger.error(LogMessages.WebsocketError, error=traceback.format_exc())
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="Exception handling feedback, please try again!",
        )
    return response


async def websocket_delete(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    if data.payload is not None:
        job_id = validate_uuid(data.payload)
        try:
            query = select(Jobs).where(Jobs.id == job_id, Jobs.userid == data.userid)
            res = session.exec(query).one()
            res.status = JobStatus.Hidden.value
            res.updated = datetime.now(UTC)
            session.add(res)
            session.commit()
            session.refresh(res)
            logger.info(
                LogMessages.JobDeleted,
                src_ip=get_client_ip(websocket),
                **data.model_dump(),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Delete, payload=res.model_dump_json()
            )
        except NoResultFound:
            logger.info(
                LogMessages.DeleteNotFound,
                job_id=job_id,
                src_ip=get_client_ip(websocket),
                **data.model_dump(),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Error.value,
                payload=f"No job ID found matching {job_id}",
            )
    else:
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="No ID specified when asking for delete!",
        )
    return response


class WebSocketJobsMessage(BaseModel):
    """the message sent when asking for jobs"""

    sessionid: UUID
    since: Optional[float] = None


async def websocket_jobs(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    # serialize the jobs out so the websocket reader can parse them
    try:
        payload = WebSocketJobsMessage.model_validate_json(data.payload or "")
        logger.debug("Getting jobs since {}", payload.since, **payload.model_dump())
        payload_timestamp = datetime.fromtimestamp(payload.since or 0.0, UTC)
        jobs = session.exec(
            select(Jobs).where(
                Jobs.userid == data.userid,
                Jobs.sessionid == payload.sessionid,
                Jobs.status != JobStatus.Hidden.value,
                or_(
                    Jobs.created > payload_timestamp,
                    (Jobs.updated is not None and Jobs.updated > payload_timestamp),
                ),
            )
        ).all()
        logger.debug("Found {} jobs", len(jobs), **payload.model_dump(mode="json"))

        response_payload = [Job.from_jobs(job, None) for job in jobs]
        response = WebSocketResponse(
            message=WebSocketMessageType.Jobs.value, payload=response_payload
        )
    except Exception as error:
        logger.error(
            "websocket_jobs error",
            error=error,
            src_ip=get_client_ip(websocket),
            **data.model_dump(),
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value, payload="Failed to get job list!"
        )
    return response
