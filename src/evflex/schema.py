from __future__ import annotations

from enum import StrEnum


class DataRole(StrEnum):
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"
    DEVELOPMENT_ABLATION = "development_ablation"


class Direction(StrEnum):
    INC = "inc"
    DEC = "dec"


DURATIONS = (15, 30, 60)
CALL_TIMES = ("19:00", "00:00", "02:00", "06:00")
FEEDERS = ("ieee13", "lv906")
