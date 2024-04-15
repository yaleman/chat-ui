from enum import StrEnum


class Urls(StrEnum):
    Sessions = "/sessions"
    AdminSessions = "/admin/sessions"
    AdminAnalyses = "/admin/analyses"
    AdminJobs = "/admin/jobs"
    AdminUsers = "/admin/users"
    Analyse = "/analyse"
    Analyses = "/analyses"
    HealthCheck = "/healthcheck"
    Job = "/job"
    Jobs = "/jobs"
    User = "/user"
