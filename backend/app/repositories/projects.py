"""projects repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project


class ProjectsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, name: str, description: str | None = None) -> Project:
        project = Project(name=name, description=description)
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def get(self, project_id: str) -> Project | None:
        return self.db.get(Project, project_id)

    def list(self, limit: int = 100, offset: int = 0) -> list[Project]:
        stmt = select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(stmt))

    def update(
        self,
        project: Project,
        name: str | None = None,
        description: str | None = None,
    ) -> Project:
        """Apply a partial update (only the fields explicitly passed)."""
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description.strip() or None
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete(self, project: Project) -> None:
        self.db.delete(project)
        self.db.commit()
