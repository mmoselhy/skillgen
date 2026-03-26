"""Tests for the detector module."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillgen.detector import detect_project
from skillgen.models import Language


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    return tmp_path


def _create_file(base: Path, relative: str, content: str = "") -> Path:
    """Create a file in the temp project, creating parent dirs as needed."""
    full = base / relative
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


class TestLanguageDetection:
    """Test language detection from file extensions."""

    def test_detect_python(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "main.py", "print('hello')")
        _create_file(tmp_project, "utils.py", "def helper(): pass")
        _create_file(tmp_project, "models.py", "class User: pass")
        info = detect_project(tmp_project)
        assert len(info.languages) >= 1
        lang_values = [li.language for li in info.languages]
        assert Language.PYTHON in lang_values

    def test_detect_typescript(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "index.ts", "export const x = 1;")
        _create_file(tmp_project, "app.tsx", "function App() {}")
        _create_file(tmp_project, "tsconfig.json", '{"compilerOptions": {}}')
        info = detect_project(tmp_project)
        lang_values = [li.language for li in info.languages]
        assert Language.TYPESCRIPT in lang_values

    def test_detect_javascript(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "index.js", "const x = 1;")
        _create_file(tmp_project, "utils.js", "function helper() {}")
        _create_file(tmp_project, "app.js", "module.exports = {}")
        _create_file(tmp_project, "package.json", '{"name": "test"}')
        info = detect_project(tmp_project)
        lang_values = [li.language for li in info.languages]
        assert Language.JAVASCRIPT in lang_values

    def test_detect_go(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "main.go", "package main\nfunc main() {}")
        _create_file(tmp_project, "handler.go", "package handler")
        _create_file(tmp_project, "go.mod", "module github.com/test/app")
        info = detect_project(tmp_project)
        lang_values = [li.language for li in info.languages]
        assert Language.GO in lang_values

    def test_detect_rust(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "main.rs", "fn main() {}")
        _create_file(tmp_project, "lib.rs", "pub mod utils;")
        _create_file(tmp_project, "Cargo.toml", '[package]\nname = "test"')
        info = detect_project(tmp_project)
        lang_values = [li.language for li in info.languages]
        assert Language.RUST in lang_values

    def test_detect_java(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "Main.java", "public class Main {}")
        _create_file(tmp_project, "App.java", "public class App {}")
        _create_file(tmp_project, "pom.xml", "<project></project>")
        info = detect_project(tmp_project)
        lang_values = [li.language for li in info.languages]
        assert Language.JAVA in lang_values

    def test_detect_cpp(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "main.cpp", "int main() {}")
        _create_file(tmp_project, "utils.hpp", "#pragma once")
        _create_file(tmp_project, "lib.h", "void foo();")
        info = detect_project(tmp_project)
        lang_values = [li.language for li in info.languages]
        assert Language.CPP in lang_values

    def test_detect_mixed_languages(self, tmp_project: Path) -> None:
        """Polyglot projects should detect all languages above 10% threshold."""
        # 5 Python files
        for i in range(5):
            _create_file(tmp_project, f"py_{i}.py", f"x = {i}")
        # 5 TypeScript files
        for i in range(5):
            _create_file(tmp_project, f"ts_{i}.ts", f"const x = {i};")
        _create_file(tmp_project, "tsconfig.json", "{}")

        info = detect_project(tmp_project)
        lang_values = [li.language for li in info.languages]
        assert Language.PYTHON in lang_values
        assert Language.TYPESCRIPT in lang_values

    def test_empty_directory(self, tmp_project: Path) -> None:
        """An empty directory should detect no languages."""
        info = detect_project(tmp_project)
        assert len(info.languages) == 0

    def test_no_source_files(self, tmp_project: Path) -> None:
        """Non-source files should not result in language detection."""
        _create_file(tmp_project, "README.md", "# Hello")
        _create_file(tmp_project, "config.yml", "key: value")
        _create_file(tmp_project, "Dockerfile", "FROM python:3.11")
        info = detect_project(tmp_project)
        assert len(info.languages) == 0


class TestFrameworkDetection:
    """Test framework detection from config files."""

    def test_detect_django(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "manage.py", "#!/usr/bin/env python")
        _create_file(tmp_project, "app.py", "x = 1")
        _create_file(tmp_project, "views.py", "y = 2")
        info = detect_project(tmp_project)
        fw_names = [fw.name for fw in info.frameworks]
        assert "Django" in fw_names

    def test_detect_flask(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "app.py", "from flask import Flask")
        _create_file(tmp_project, "routes.py", "x = 1")
        _create_file(tmp_project, "requirements.txt", "flask==2.0\nrequests")
        info = detect_project(tmp_project)
        fw_names = [fw.name for fw in info.frameworks]
        assert "Flask" in fw_names

    def test_detect_fastapi(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "main.py", "from fastapi import FastAPI")
        _create_file(tmp_project, "routes.py", "x = 1")
        _create_file(tmp_project, "requirements.txt", "fastapi\nuvicorn")
        info = detect_project(tmp_project)
        fw_names = [fw.name for fw in info.frameworks]
        assert "FastAPI" in fw_names

    def test_detect_nextjs(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "next.config.js", "module.exports = {}")
        _create_file(tmp_project, "pages/index.tsx", "export default function Home() {}")
        _create_file(tmp_project, "tsconfig.json", "{}")
        info = detect_project(tmp_project)
        fw_names = [fw.name for fw in info.frameworks]
        assert "Next.js" in fw_names

    def test_detect_react_from_package_json(self, tmp_project: Path) -> None:
        _create_file(
            tmp_project,
            "package.json",
            '{"dependencies": {"react": "^18.0.0"}}',
        )
        _create_file(tmp_project, "App.jsx", "function App() {}")
        _create_file(tmp_project, "index.js", "import React from 'react';")
        info = detect_project(tmp_project)
        fw_names = [fw.name for fw in info.frameworks]
        assert "React" in fw_names

    def test_detect_spring_from_pom(self, tmp_project: Path) -> None:
        _create_file(
            tmp_project,
            "pom.xml",
            "<dependency><groupId>org.springframework</groupId></dependency>",
        )
        _create_file(tmp_project, "App.java", "public class App {}")
        _create_file(tmp_project, "Controller.java", "public class Controller {}")
        info = detect_project(tmp_project)
        fw_names = [fw.name for fw in info.frameworks]
        assert "Spring" in fw_names


class TestSkipDirectories:
    """Test that vendored and generated directories are skipped."""

    def test_skip_node_modules(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "index.ts", "export const x = 1;")
        _create_file(tmp_project, "app.ts", "export const y = 2;")
        _create_file(tmp_project, "tsconfig.json", "{}")
        # Should be ignored
        for i in range(100):
            _create_file(tmp_project, f"node_modules/pkg/file_{i}.js", "module.exports = {}")
        info = detect_project(tmp_project)
        # Should only detect the 2 TS files, not the 100 JS files in node_modules
        for li in info.languages:
            if li.language == Language.TYPESCRIPT:
                assert li.file_count == 2

    def test_skip_pycache(self, tmp_project: Path) -> None:
        _create_file(tmp_project, "main.py", "x = 1")
        _create_file(tmp_project, "utils.py", "y = 2")
        _create_file(tmp_project, "__pycache__/main.cpython-311.pyc", "binary")
        info = detect_project(tmp_project)
        for li in info.languages:
            if li.language == Language.PYTHON:
                assert li.file_count == 2


class TestProjectInfo:
    """Test that ProjectInfo is correctly populated."""

    def test_file_counts(self, tmp_project: Path) -> None:
        for i in range(10):
            _create_file(tmp_project, f"src/file_{i}.py", f"x = {i}")
        info = detect_project(tmp_project)
        assert info.source_files == 10

    def test_percentage_calculation(self, tmp_project: Path) -> None:
        for i in range(7):
            _create_file(tmp_project, f"py_{i}.py", f"x = {i}")
        for i in range(3):
            _create_file(tmp_project, f"ts_{i}.ts", f"const x = {i};")
        _create_file(tmp_project, "tsconfig.json", "{}")
        info = detect_project(tmp_project)
        for li in info.languages:
            if li.language == Language.PYTHON:
                assert li.percentage == 70.0
            elif li.language == Language.TYPESCRIPT:
                assert li.percentage == 30.0

    def test_primary_language(self, tmp_project: Path) -> None:
        for i in range(8):
            _create_file(tmp_project, f"py_{i}.py", f"x = {i}")
        for i in range(2):
            _create_file(tmp_project, f"ts_{i}.ts", f"const x = {i};")
        _create_file(tmp_project, "tsconfig.json", "{}")
        info = detect_project(tmp_project)
        assert info.primary_language.language == Language.PYTHON
