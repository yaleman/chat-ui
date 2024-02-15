from datetime import datetime
from sqlite3 import Connection, Cursor, Row, connect
import sys
from typing import Any, List, Optional
from uuid import uuid4

from loguru import logger

from chat_ui.models import Job, JobDetail, NewJob, UserDetail, UserForm


# TABLES
#
# users
# - userid
# - name
# - created

# jobs
# - id
# - userid
# - status
# - created
# - prompt
# - response
# - request_type
# - runtime

USERS_TABLE = "users"
JOBS_TABLE = "jobs"


def dict_factory(cursor: Cursor, row: Row) -> dict[str, Any]:
    """turns sqlite rows into dictionaries"""
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}


class DB:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn = self.create_connection()
        self.conn.row_factory = dict_factory
        self.create_tables()

    def create_connection(
        self,
    ) -> Connection:
        """create the database connection"""
        conn = connect(self.db_path, check_same_thread=False)
        return conn

    def create_tables(self) -> None:
        """create the tables"""
        cur = self.conn.cursor()
        try:
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS
                    {USERS_TABLE}(userid UNIQUE NOT NULL, name NOT NULL, created NOT NULL, updated)
                    """
            )
        except Exception as error:
            logger.error("Error creating users table: {}", error)
            sys.exit(1)
        try:
            cur.execute(
                f"""CREATE TABLE IF NOT EXISTS
                    {JOBS_TABLE}(id UNIQUE NOT NULL, userid NOT NULL, status NOT NULL, created NOT NULL, prompt NOT NULL, response, request_type NOT NULL, runtime)
                    """
            )
        except Exception as error:
            logger.error("Error creating jobs table: {}", error)
            sys.exit(1)
        self.conn.commit()

    def get_jobs(self, userid: str, include_hidden: bool = False) -> List[Job]:
        """gets the jobs for a userid"""
        try:
            query = f"SELECT id,userid,status,created from {JOBS_TABLE} where userid=:userid"
            if not include_hidden:
                query += " AND status != 'hidden'"
            cur = self.conn.cursor()
            cur.execute(query, {"userid": userid})
            res = cur.fetchall()
            if res is None:
                return []
            return [Job(**row) for row in res]

        except Exception as error:
            logger.error("Error pulling jobs for user: {}", error)
            return []

    def get_job(self, userid: str, id: str) -> Optional[JobDetail]:
        """gets the job for a given user/id combo"""
        try:
            query = f"SELECT * from {JOBS_TABLE} where userid=:userid AND id=:id"
            cur = self.conn.cursor()
            cur.execute(
                query,
                {
                    "userid": userid,
                    "id": id,
                },
            )
            res = cur.fetchone()
            if res is None:
                logger.debug("Failed to find job for userid={} id={}", userid, id)
                return None
            return JobDetail(**res)
        except Exception as error:
            logger.error("Error pulling jobs for user: {}", error)
            return None

    def create_user(self, userform: UserForm) -> Optional[UserDetail]:
        """gets the jobs for a userid"""
        try:
            query = f"""
                INSERT INTO {USERS_TABLE} (userid, name, created)
                VALUES (:userid, :name, :created)
                ON CONFLICT(userid) DO UPDATE
                SET name=:name, updated=unixepoch('now','subsec')"""
            cur = self.conn.cursor()
            cur.execute(
                query,
                {
                    "userid": userform.userid,
                    "name": userform.name,
                    "created": datetime.utcnow().timestamp(),
                },
            )
            cur.execute(
                f"SELECT userid, name, created, updated from {USERS_TABLE} where userid=:userid",
                {"userid": userform.userid},
            )
            row = dict(cur.fetchone())
            logger.debug(row)
            self.conn.commit()
            response = UserDetail(**row)
            return response
        except Exception as error:
            logger.error("Error creating user: {}", error)
        return None

    def has_user(self, userid: str) -> bool:
        """gets the jobs for a userid"""
        try:
            query = "SELECT name from {USERS_TABLE} where userid=:userid"
            cur = self.conn.cursor()
            cur.execute(query, {"userid": userid})
            return cur.fetchone() is not None
        except Exception as error:
            logger.error("Error checking for user: {}", error)
            return False

    def create_job(self, job: NewJob) -> Job:
        """stores the state of a job"""

        job_data = job.model_dump()
        job_data["id"] = str(uuid4())
        job_data["status"] = "created"
        job_data["created"] = datetime.utcnow().timestamp()

        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO jobs (id, userid, status, created, prompt, request_type)
            VALUES (:id, :userid, :status, :created, :prompt, :request_type)""",
            job_data,
        )
        self.conn.commit()
        logger.debug("Stored job: {}", job)

        cur.execute(
            "SELECT id, userid, status, created from jobs where id=:id AND userid=:userid",
            job_data,
        )
        res = Job(**cur.fetchone())
        logger.debug("Returning job data {}", res)
        return res

    def hide_job(self, userid: str, id: str) -> Optional[JobDetail]:
        """update the db to hide a job"""
        cur = self.conn.cursor()
        cur.execute(
            """UPDATE jobs
            SET status="hidden"
            WHERE userid=:userid AND id=:id
            """,
            {
                "userid": userid,
                "id": id,
            },
        )
        self.conn.commit()
        return self.get_job(userid=userid, id=id)

    def update_job(self, job: JobDetail) -> JobDetail:
        """update the db with the state of the job"""
        cur = self.conn.cursor()
        cur.execute(
            """UPDATE jobs
            SET status=:status, response=:response, runtime=:runtime
            WHERE id=:id
            """,
            job.model_dump(),
        )
        self.conn.commit()
        res = self.get_job(userid=job.userid, id=job.id)
        if res is None:
            raise ValueError("Updated a job and then couldn't find it?")
        return res

    def error_job(self, job: JobDetail) -> None:
        """update the db to say there was an error"""
        cur = self.conn.cursor()
        cur.execute(
            """UPDATE jobs
            SET status="error"
            WHERE id=:id
            """,
            job.model_dump(),
        )
        self.conn.commit()
