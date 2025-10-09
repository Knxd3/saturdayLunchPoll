"""
Data models.
"""
from dataclasses import dataclass
from typing import List

@dataclass
class PollOption:
    id: int
    text: str

@dataclass
class Poll:
    id: int
    question: str
    options: List[PollOption]