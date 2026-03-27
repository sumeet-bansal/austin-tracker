"""Shared types for the Austin PCT tracker."""

from dataclasses import dataclass
from typing import TypedDict


class Post(TypedDict, total=False):
    id: str
    title: str
    created_at: str
    trail_mile: float
    body: str
    photo_url: str


class TrackerData(TypedDict, total=False):
    current_mile: float
    lat: float
    lng: float
    day: int
    pace_mi_per_day: float
    elevation_gain_display: str
    pct_complete: float
    posts: list[Post]


@dataclass
class Config:
    token: str
    channel: str
    mapbox_token: str


@dataclass
class PostDecision:
    should_post: bool
    include_posts: list[Post]
