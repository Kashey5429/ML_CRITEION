"""File library and automatic snapshot preparation for the comparison wizard."""

import time
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ml_criterion.application.experiments import ApplicationError
from ml_criterion.domain.specs import DatasetSpec
from ml_criterion.persistence.models import Dataset, DatasetVersion, FileImport, Job


class Selection(BaseModel):
    import_id: UUID | None = None
    features: list[str] = Field(default_factory=list, max_length=100)
    target: str = ""
    refresh: bool = False


def import_view(item):
    return {
        "id": item.id,
        "dataset_id": item.dataset_id,
        "filename": item.filename,
        "status": item.status,
        "profile": item.profile,
        "error_code": item.error_code,
        "created_at": item.created_at,
    }


def register_import_routes(app, sessions, settings):
    def cleanup_uploads():
        root = Path(settings.upload_root)
        cutoff = time.time() - settings.upload_retention_hours * 3600
        with sessions() as session:
            active = {
                str(i)
                for i in session.scalars(
                    select(FileImport.id).where(FileImport.status.in_(["queued", "running"]))
                )
            }
            active.update(
                payload["file_id"]
                for payload in session.scalars(
                    select(Job.payload).where(
                        Job.kind == "import", Job.state.in_(["queued", "leased"])
                    )
                )
            )
        for path in root.glob("*.csv"):
            if path.stem not in active and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)

    @app.post("/api/v1/imports", status_code=202)
    async def upload(
        request: Request,
        filename: str = Query(min_length=1, max_length=255),
        encoding: Literal["auto", "utf-8-sig", "cp1251"] = "auto",
        delimiter: Literal["auto", ",", ";", "\t"] = "auto",
        dataset_id: UUID | None = None,
    ):
        if not filename.lower().endswith(".csv"):
            raise ApplicationError(
                "Поддерживаются файлы CSV. Сохраните таблицу в этом формате.", 422
            )
        if dataset_id:
            with sessions() as session:
                dataset = session.get(Dataset, dataset_id)
                if not dataset or dataset.spec.get("kind") != "file":
                    raise ApplicationError("Файловый источник не найден.", 404)
        root = Path(settings.upload_root)
        root.mkdir(parents=True, exist_ok=True)
        cleanup_uploads()
        item_id = uuid4()
        path = root / (str(item_id) + ".csv")
        size = 0
        try:
            with path.open("xb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    output.write(chunk)
            if not size:
                raise ApplicationError("Файл пуст.", 422)
            with sessions.begin() as session:
                if dataset_id is None:
                    dataset = Dataset(spec={"kind": "file", "name": filename})
                    session.add(dataset)
                    session.flush()
                    dataset_id = dataset.id
                item = FileImport(id=item_id, dataset_id=dataset_id, filename=filename)
                session.add(item)
                session.flush()
                session.add(
                    Job(
                        kind="import",
                        import_id=item.id,
                        payload={
                            "kind": "import",
                            "file_id": str(item.id),
                            "encoding": encoding,
                            "delimiter": delimiter,
                            "timeout_seconds": 300,
                        },
                    )
                )
                response = import_view(item)
            return response
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @app.get("/api/v1/imports/{import_id}")
    def get_import(import_id: UUID):
        with sessions() as session:
            item = session.get(FileImport, import_id)
            if not item:
                raise ApplicationError("Загрузка не найдена.", 404)
            return import_view(item)

    @app.post("/api/v1/imports/{import_id}/retry", status_code=202)
    def retry_import(import_id: UUID):
        with sessions.begin() as session:
            original = session.get(FileImport, import_id, with_for_update=True)
            if not original:
                raise ApplicationError("Загрузка не найдена.", 404)
            if original.status in {"queued", "running"}:
                return import_view(original)
            previous = session.scalar(select(Job).where(Job.import_id == import_id))
            if not previous:
                raise ApplicationError("Исходный файл недоступен. Загрузите его повторно.", 410)
            file_id = previous.payload["file_id"]
            if not (Path(settings.upload_root) / (file_id + ".csv")).is_file():
                raise ApplicationError("Исходный файл уже очищен. Загрузите его повторно.", 410)
            # A new import preserves every old selection and benchmark snapshot.
            item = FileImport(dataset_id=original.dataset_id, filename=original.filename)
            session.add(item)
            session.flush()
            session.add(
                Job(
                    kind="import",
                    import_id=item.id,
                    payload={
                        **previous.payload,
                        "file_id": file_id,
                    },
                )
            )
            return import_view(item)

    @app.get("/api/v1/datasets/{dataset_id}/imports")
    def list_imports(
        dataset_id: UUID, limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        with sessions() as session:
            return [
                import_view(i)
                for i in session.scalars(
                    select(FileImport)
                    .where(FileImport.dataset_id == dataset_id)
                    .order_by(FileImport.created_at.desc(), FileImport.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ]

    @app.post("/api/v1/datasets/{dataset_id}/prepare", status_code=202)
    def prepare_selection(dataset_id: UUID, selection: Selection):
        with sessions.begin() as session:
            dataset = session.get(Dataset, dataset_id, with_for_update=True)
            if not dataset:
                raise ApplicationError("Источник не найден.", 404)
            file_source = dataset.spec.get("kind") == "file"
            display = {}
            if file_source:
                item = session.get(FileImport, selection.import_id) if selection.import_id else None
                if not item or item.dataset_id != dataset_id or item.status != "ready":
                    raise ApplicationError("Дождитесь проверки файла.", 422)
                columns = {c["key"]: c for c in item.profile["columns"]}
                chosen = [*selection.features, selection.target]
                if (
                    not selection.features
                    or len(set(chosen)) != len(chosen)
                    or any(c not in columns or not columns[c]["usable"] for c in chosen)
                ):
                    raise ApplicationError("Выберите разные числовые столбцы без пропусков.", 422)
                display = {c: columns[c]["name"] for c in chosen}
                source = DatasetSpec(
                    name=item.filename[:128],
                    source_schema="uploads",
                    source_table=item.profile["table"],
                    id_column="row_id",
                    features=tuple(selection.features),
                    target=selection.target,
                ).model_dump(mode="json")
                key = {
                    "import_id": str(item.id),
                    "features": selection.features,
                    "target": selection.target,
                }
            else:
                source, key = dataset.spec, None
            versions = session.scalars(
                select(DatasetVersion)
                .where(
                    DatasetVersion.dataset_id == dataset_id,
                    DatasetVersion.status.in_(["ready", "queued", "running"]),
                )
                .order_by(DatasetVersion.created_at.desc())
            ).all()
            existing = next((v for v in versions if v.selection == key), None)
            if existing and (not selection.refresh or existing.status != "ready"):
                return {"id": existing.id, "status": existing.status}
            version = DatasetVersion(dataset_id=dataset_id, selection=key)
            session.add(version)
            session.flush()
            session.add(
                Job(
                    kind="snapshot",
                    version_id=version.id,
                    payload={
                        "kind": "snapshot",
                        "source": source,
                        "file_source": file_source,
                        "display_columns": display,
                        "source_name": source["name"],
                        "version_id": str(version.id),
                        "timeout_seconds": 300,
                    },
                )
            )
            return {"id": version.id, "status": version.status}
