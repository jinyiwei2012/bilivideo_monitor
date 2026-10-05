"""Repository interfaces for database-backed UI queries and mutations."""

from .monitor import MonitorRepository
from .prediction import PredictionRepository
from .read_model import ReadModelRepository
from .viewer import ViewerRepository

__all__ = ["MonitorRepository", "PredictionRepository", "ReadModelRepository", "ViewerRepository"]
