import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

import appdirs
from peewee import DoesNotExist, Model, TextField
from playhouse.sqlite_ext import JSONField

from bw_projects.errors import NoActiveProject
from bw_projects.filesystem import safe_filename
from bw_projects.sqlite import SubstitutableDatabase


class ProjectDataset(Model):
    name = TextField(index=True, unique=True)
    attributes = JSONField()

    def __str__(self):
        return "Project: {}".format(self.name)

    def __lt__(self, other):
        if not isinstance(other, ProjectDataset):
            raise TypeError
        else:
            return self.name.lower() < other.name.lower()


class ProjectManager(Iterable):
    _basic_directories = (
        "backups",
        "intermediate",
        "lci",
        "processed",
    )
    _is_temp_dir = False
    read_only = False

    def __init__(self, folder: str = None):
        self._base_data_dir, self._base_logs_dir = self._get_base_directories(folder)
        self._create_base_directories()
        self.db = SubstitutableDatabase(
            f"{self._base_data_dir}/projects.db", [ProjectDataset]
        )
        self._project_name = None

    def __iter__(self):
        for project_ds in ProjectDataset.select():
            yield project_ds

    def __contains__(self, name: str) -> bool:
        return ProjectDataset.select().where(ProjectDataset.name == name).count() > 0

    def __len__(self) -> int:
        return ProjectDataset.select().count()

    def __repr__(self) -> str:
        if len(self) > 20:
            return (
                "Brightway2 projects manager with {} objects, including:"
                "{}\nUse `sorted(projects)` to get full list, "
                "`projects.report()` to get\n\ta report on all projects."
            ).format(
                len(self),
                "".join(
                    ["\n\t{}".format(x) for x in sorted([x.name for x in self])[:10]]
                ),
            )
        else:
            return (
                "Brightway2 projects manager with {} objects:{}"
                "\nUse `projects.report()` to get a report on all projects."
            ).format(
                len(self),
                "".join(["\n\t{}".format(x) for x in sorted([x.name for x in self])]),
            )

    # ---- Internal functions for managing projects
    def _get_base_directories(self, folder: str = None) -> tuple[Path, Path]:
        if folder:
            envvar = folder
        elif os.getenv("BRIGHTWAY_DIR"):
            envvar = os.getenv("BRIGHTWAY_DIR")
        else:
            label = "Brightway3"
            data_dir = Path(appdirs.user_data_dir(label, "pylca"))
            logs_dir = Path(appdirs.user_log_dir(label, "pylca"))
            return data_dir, logs_dir
        os.makedirs(envvar, exist_ok=True)
        logs_dir = f"{envvar}/logs"
        os.makedirs(logs_dir, exist_ok=True)
        return envvar, logs_dir

    def _create_base_directories(self) -> None:
        os.makedirs(self._base_data_dir, exist_ok=True)
        os.makedirs(self._base_logs_dir, exist_ok=True)

    @property
    def current(self) -> str:
        return self._project_name

    def set_current(self, name, **kwargs) -> None:
        self._project_name = str(name)

        # Need to allow writes when creating a new project
        # for new metadata stores
        self.read_only = False
        self.create_project(name, **kwargs)

    # Public API
    @property
    def dir(self) -> Path:
        if self.current:
            return Path(self._base_data_dir) / safe_filename(self.current)
        else:
            raise NoActiveProject

    @property
    def logs_dir(self) -> Path:
        if self.current:
            return Path(self._base_logs_dir) / safe_filename(self.current)
        else:
            raise NoActiveProject

    @property
    def output_dir(self) -> Path:
        """Get directory for output files.

        Uses environment variable ``BRIGHTWAY_OUTPUT_DIR``;
        ``preferences['output_dir']``; or directory ``output``
        in current project.

        Returns output directory path.

        """
        ep = os.getenv("BRIGHTWAY_OUTPUT_DIR")
        if ep and os.path.exists(ep):
            return ep
        return self.request_directory("output")

    def create_project(self, name: str = None, **kwargs) -> None:
        name = name or self.current

        try:
            self.dataset = ProjectDataset.get(ProjectDataset.name == name)
        except DoesNotExist:
            self.dataset = ProjectDataset.create(attributes=kwargs, name=name)
        os.makedirs(self.dir, exist_ok=True)
        for dir_name in self._basic_directories:
            os.makedirs(self.dir / dir_name, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

    def copy_project(self, new_name: str, switch: bool = True) -> None:
        """Copy current project to a new project named ``new_name``. If ``switch``,
        switch to new project."""
        if new_name in self:
            raise ValueError("Project {} already exists".format(new_name))
        fp = self._base_data_dir / safe_filename(new_name)
        if fp.exists():
            raise ValueError("Project directory already exists")
        if self.current is None:
            raise NoActiveProject
        project_data = ProjectDataset.get(
            ProjectDataset.name == self.current
        ).attributes
        ProjectDataset.create(attributes=project_data, name=new_name)
        shutil.copytree(self.dir, fp, ignore=lambda x, y: ["write-lock"])
        os.makedirs(self._base_logs_dir / safe_filename(new_name), exist_ok=True)
        if switch:
            self.set_current(new_name)

    def request_directory(self, name: str) -> Path:
        """Return the absolute path to the subdirectory ``dirname``,
        creating it if necessary.

        Returns ``False`` if directory can't be created."""
        fp = self.dir / str(name)
        os.makedirs(fp, exist_ok=True)
        if not fp.is_dir():
            return False
        return fp

    def _use_temp_directory(self) -> None:
        """Point the ProjectManager towards a temporary directory instead of
        `user_data_dir`.

        Used exclusively for tests."""
        if not self._is_temp_dir:
            self._orig_base_data_dir = self._base_data_dir
            self._orig_base_logs_dir = self._base_logs_dir
        temp_dir = Path(tempfile.mkdtemp())
        self._base_data_dir = temp_dir / "data"
        self._base_logs_dir = temp_dir / "logs"
        self.db.change_path(":memory:")
        self._is_temp_dir = True
        return temp_dir

    def _restore_orig_directory(self) -> None:
        """Point the ProjectManager back to original directories.

        Used exclusively in tests."""
        if not self._is_temp_dir:
            return
        self._base_data_dir = self._orig_base_data_dir
        del self._orig_base_data_dir
        self._base_logs_dir = self._orig_base_logs_dir
        del self._orig_base_logs_dir
        self.db.change_path(self._base_data_dir / "projects.db")
        self._is_temp_dir = False

    def delete_project(self, name: str = None, delete_dir: bool = False) -> str:
        """Delete project ``name``, or the current project.

        ``name`` is the project to delete. If ``name`` is not provided,
        delete the current project.

        By default, the underlying project directory is not deleted;
        only the project name is removed from the list of active projects.
        If ``delete_dir`` is ``True``, then also delete the project directory.

        If deleting the current project, this function sets the current directory
        to ``default`` if it exists, or to a random project.

        Returns the current project."""
        if self._project_name is None:
            raise NoActiveProject

        victim = name or self.current
        if victim not in self:
            raise ValueError("{} is not a project".format(victim))

        ProjectDataset.delete().where(ProjectDataset.name == victim).execute()

        if delete_dir:
            dir_path = self._base_data_dir / safe_filename(victim)
            assert dir_path.is_dir(), "Can't find project directory"
            shutil.rmtree(dir_path)

        if name is None or name == self.current:
            try:
                self.set_current(next(iter(self)).name)
            except StopIteration:
                self._project_name = None
        return self.current

    def purge_deleted_directories(self) -> int:
        """Delete project directories for projects which are no longer registered.

        Returns number of directories deleted."""
        registered = {safe_filename(obj.name) for obj in self}
        bad_directories = [
            self._base_data_dir / dirname
            for dirname in os.listdir(self._base_data_dir)
            if (self._base_data_dir / dirname).is_dir() and dirname not in registered
        ]

        for fp in bad_directories:
            shutil.rmtree(fp)

        return len(bad_directories)


projects = ProjectManager()
