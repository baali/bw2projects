"""Test cases for the __project__ module."""
import os
import random
import shutil
import string
import sys
import tempfile
import unittest
from pathlib import Path

from slugify import slugify

from bw_projects import projects
from bw_projects.errors import NoActiveProjectError
from bw_projects.helpers import DatabaseHelper
from bw_projects.model import Project
from bw_projects.project import ProjectManager

from .conftest import check_dir


class TestProjects(unittest.TestCase):
    def setUp(self):
        projects._orig_base_data_dir = projects._base_data_dir
        projects._orig_base_logs_dir = projects._base_logs_dir
        temp_dir = Path(tempfile.mkdtemp())
        projects._base_data_dir = temp_dir / "data"
        projects._base_logs_dir = temp_dir / "logs"
        DatabaseHelper.init_db(":memory:", [Project])
        self.tempdir = temp_dir

        self.current = "".join(random.choices(string.ascii_lowercase, k=18))
        projects.set_current(self.current)
        self.assertEqual(self.current, projects.current)
        self.projects = projects

    def tearDown(self):
        if hasattr(self.projects, "_lock"):
            try:
                self.projects._lock.release()
            except (RuntimeError):
                pass
        shutil.rmtree(self.tempdir)

    def test_project_default(self):
        self.assertTrue(self.projects.current)
        self.assertEqual(self.current, self.projects.current)
        self.assertTrue(check_dir(self.projects.dir.absolute()))
        self.assertTrue(check_dir(self.projects.logs_dir.absolute()))
        self.assertEqual(len(self.projects), 1)

    def test_create_project(self):
        self.assertEqual(len(self.projects), 1)
        self.projects.create_project("a-new-project")
        self.assertEqual(len(self.projects), 2)
        self.assertNotEqual(projects.current, "a-new-project")
        self.assertTrue("a-new-project" in self.projects)

    def test_set_current(self):
        new_project_name = "".join(random.choices(string.ascii_lowercase, k=18))
        self.assertNotEqual(projects.current, new_project_name)
        self.assertFalse(
            check_dir(f"{self.projects._base_data_dir}/{slugify(new_project_name)}")
        )
        self.projects.set_current(new_project_name)
        self.assertTrue(
            check_dir(f"{self.projects._base_data_dir}/{slugify(new_project_name)}")
        )

    @unittest.skip("Don't run this test. It will clean up existing projects")
    def test_project_creation(self):
        """No arguments, initializing project instance"""
        projects = ProjectManager()
        self.assertGreater(len(projects), 1)
        self.assertEqual(projects.current, None)
        shutil.rmtree(projects.dir)

    @unittest.skipUnless(sys.platform.startswith("win"), "requires Windows")
    def test_windows_path(self):
        """Logic to confirm we handle windows path length limitation"""
        pass

    def test_project_folder(self):
        tmpdirname = tempfile.gettempdir()
        projects = ProjectManager(tmpdirname)
        self.assertEqual(projects.current, None)
        self.assertEqual(len(projects), 0)
        with self.assertRaises(NoActiveProjectError):
            projects.dir

    def test_project_with_folder_priority(self):
        """Pass folder argument and confirm ENV variable doesn't get used"""
        os.environ["BRIGHTWAY_DIR"] = os.getcwd()
        tmpdirname = tempfile.gettempdir()
        projects = ProjectManager(tmpdirname)
        self.assertEqual(projects.current, None)
        self.assertEqual(len(projects), 0)
        with self.assertRaises(NoActiveProjectError):
            projects.dir
        self.assertTrue(Path(projects._base_data_dir).is_relative_to(tmpdirname))
        self.assertFalse(
            Path(projects._base_data_dir).is_relative_to(os.getenv("BRIGHTWAY_DIR"))
        )
        del os.environ["BRIGHTWAY_DIR"]

    def test_project_with_env_variable(self):
        """Pass folder argument and confirm ENV variable doesn't get used"""
        tmpdirname = tempfile.gettempdir()
        os.environ["BRIGHTWAY_DIR"] = tmpdirname
        projects = ProjectManager()
        self.assertTrue(check_dir(f"{projects._base_data_dir}"))
        self.assertTrue(check_dir(f"{projects._base_logs_dir}"))
        self.assertEqual(projects.current, None)
        self.assertEqual(len(projects), 0)
        with self.assertRaises(NoActiveProjectError):
            projects.dir
        del os.environ["BRIGHTWAY_DIR"]

    def test_multiple_projects_different_location(self):
        folder_1 = "".join(random.choices(string.ascii_lowercase, k=8))
        self.assertFalse(check_dir(folder_1))
        project_1 = ProjectManager(folder_1)
        self.assertEqual(project_1.current, None)
        DatabaseHelper.sqlite_database.close()

        folder_2 = "".join(random.choices(string.ascii_lowercase, k=8))
        self.assertFalse(check_dir(folder_2))
        project_2 = ProjectManager(folder_2)
        self.assertEqual(project_2.current, None)
        DatabaseHelper.sqlite_database.close()

        self.assertNotEqual(project_1._base_data_dir, project_2._base_data_dir)

        # Cleanup
        shutil.rmtree(project_1._base_data_dir)
        shutil.rmtree(project_2._base_data_dir)


if __name__ == "__main__":
    unittest.main()
