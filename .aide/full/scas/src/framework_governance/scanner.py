from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from .models import Component, ScanResult


KNOWN_COMPONENTS: dict[str, tuple[str, str, str]] = {
    "@angular/core": ("Angular", "framework", "npm"),
    "angular": ("Angular", "framework", "npm"),
    "react": ("React", "framework", "npm"),
    "next": ("Next.js", "framework", "npm"),
    "vue": ("Vue.js", "framework", "npm"),
    "nuxt": ("Nuxt", "framework", "npm"),
    "express": ("Express", "framework", "npm"),
    "@nestjs/core": ("NestJS", "framework", "npm"),
    "plotly.js": ("Plotly.js", "library", "npm"),
    "rxjs": ("RxJS", "library", "npm"),
    "typescript": ("TypeScript", "language-tooling", "npm"),
    "spring-boot": ("Spring Boot", "framework", "maven"),
    "org.springframework.boot": ("Spring Boot", "framework", "maven"),
    "org.springframework": ("Spring Framework", "framework", "maven"),
    "django": ("Django", "framework", "pypi"),
    "fastapi": ("FastAPI", "framework", "pypi"),
    "flask": ("Flask", "framework", "pypi"),
    "pydantic": ("Pydantic", "library", "pypi"),
    "numpy": ("NumPy", "library", "pypi"),
    "pandas": ("Pandas", "library", "pypi"),
    "pytest": ("pytest", "test-framework", "pypi"),
    "microsoft.aspnetcore": ("ASP.NET Core", "framework", "nuget"),
    "newtonsoft.json": ("Newtonsoft.Json", "library", "nuget"),
}

SOURCE_PATTERNS: list[tuple[re.Pattern[str], tuple[str, str, str]]] = [
    (re.compile(r"from\s+['\"]@angular/|@Component\s*\("), ("Angular", "framework", "npm")),
    (re.compile(r"from\s+['\"]react['\"]|React\."), ("React", "framework", "npm")),
    (re.compile(r"from\s+fastapi\s+import"), ("FastAPI", "framework", "pypi")),
    (re.compile(r"from\s+django\.|import\s+django"), ("Django", "framework", "pypi")),
    (re.compile(r"from\s+flask\s+import"), ("Flask", "framework", "pypi")),
    (re.compile(r"org\.springframework"), ("Spring Framework", "framework", "maven")),
    (re.compile(r"Microsoft\.AspNetCore"), ("ASP.NET Core", "framework", "nuget")),
]


class RepositoryScanner:
    def __init__(self, scanner_config: dict[str, Any] | None = None):
        self.config = scanner_config or {}
        self.excluded = set(self.config.get("exclude_directories", []))
        self.warnings: list[str] = []

    def scan(self, repository: str | Path) -> ScanResult:
        root = Path(repository).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Repository is not a directory: {root}")

        components: list[Component] = []
        parsers = {
            "package.json": self._parse_package_json,
            "package-lock.json": self._parse_package_lock,
            "requirements.txt": self._parse_requirements,
            "pyproject.toml": self._parse_pyproject,
            "pom.xml": self._parse_pom,
            "go.mod": self._parse_go_mod,
        }

        for path in self._walk(root):
            try:
                parser = parsers.get(path.name)
                if parser:
                    components.extend(parser(path, root))
                elif path.suffix.lower() == ".csproj":
                    components.extend(self._parse_csproj(path, root))
                elif path.name.lower() in {"dockerfile", "containerfile"}:
                    components.extend(self._parse_containerfile(path, root))
                elif path.suffix.lower() in {".gradle", ".kts"}:
                    components.extend(self._parse_gradle(path, root))
            except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
                self.warnings.append(f"Could not parse {path.relative_to(root)}: {exc}")

        if self.config.get("source_evidence", True):
            components.extend(self._scan_source_evidence(root))

        merged = self._merge_components(components)
        return ScanResult(str(root), sorted(merged, key=lambda item: item.key()), self.warnings)

    def _walk(self, root: Path) -> Iterable[Path]:
        for path in root.rglob("*"):
            if any(part in self.excluded for part in path.relative_to(root).parts):
                continue
            if path.is_file():
                yield path

    def _parse_package_json(self, path: Path, root: Path) -> list[Component]:
        data = json.loads(path.read_text(encoding="utf-8"))
        result: list[Component] = []
        relative = str(path.relative_to(root))
        for field, scope in (("dependencies", "direct"), ("devDependencies", "development")):
            for package, version in data.get(field, {}).items():
                result.append(self._component(package, _clean_version(version), "npm", relative, scope))
        node_version = data.get("engines", {}).get("node")
        if node_version:
            result.append(
                Component("Node.js", _clean_version(node_version), "runtime", "runtime", relative,
                          evidence=[f"{relative}:engines.node"], purl=None)
            )
        return result

    def _parse_package_lock(self, path: Path, root: Path) -> list[Component]:
        data = json.loads(path.read_text(encoding="utf-8"))
        relative = str(path.relative_to(root))
        result: list[Component] = []
        packages = data.get("packages", {})
        if isinstance(packages, dict):
            for key, value in packages.items():
                if not key.startswith("node_modules/") or not isinstance(value, dict):
                    continue
                name = key.split("node_modules/")[-1]
                result.append(
                    self._component(name, value.get("version"), "npm", relative,
                                    "resolved-development" if value.get("dev") else "resolved")
                )
        elif isinstance(data.get("dependencies"), dict):
            for name, value in data["dependencies"].items():
                if isinstance(value, dict):
                    result.append(self._component(name, value.get("version"), "npm", relative, "resolved"))
        return result

    def _parse_requirements(self, path: Path, root: Path) -> list[Component]:
        relative = str(path.relative_to(root))
        result: list[Component] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-", "git+")):
                continue
            match = re.match(r"([A-Za-z0-9_.-]+)\s*(?:===|==|~=|>=|<=|>|<)?\s*([^;\s]+)?", line)
            if match:
                result.append(self._component(match.group(1), _clean_version(match.group(2)), "pypi", relative))
        return result

    def _parse_pyproject(self, path: Path, root: Path) -> list[Component]:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        relative = str(path.relative_to(root))
        result: list[Component] = []
        dependencies = data.get("project", {}).get("dependencies", [])
        for value in dependencies:
            match = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)", value)
            if match:
                result.append(self._component(match.group(1), _clean_version(match.group(2)), "pypi", relative))
        requires_python = data.get("project", {}).get("requires-python")
        if requires_python:
            result.append(
                Component("Python", _clean_version(requires_python), "runtime", "runtime", relative,
                          evidence=[f"{relative}:project.requires-python"])
            )
        return result

    def _parse_pom(self, path: Path, root: Path) -> list[Component]:
        tree = ET.parse(path)
        xml_root = tree.getroot()
        namespace = ""
        if xml_root.tag.startswith("{"):
            namespace = xml_root.tag.split("}")[0] + "}"
        relative = str(path.relative_to(root))
        properties: dict[str, str] = {}
        properties_node = xml_root.find(f"{namespace}properties")
        if properties_node is not None:
            properties = {child.tag.split("}")[-1]: (child.text or "") for child in properties_node}

        result: list[Component] = []
        parent = xml_root.find(f"{namespace}parent")
        if parent is not None:
            group = _xml_text(parent, f"{namespace}groupId")
            artifact = _xml_text(parent, f"{namespace}artifactId")
            version = _resolve_property(_xml_text(parent, f"{namespace}version"), properties)
            if group == "org.springframework.boot" and artifact:
                result.append(self._component("Spring Boot", version, "maven", relative))

        for dependency in xml_root.findall(f".//{namespace}dependency"):
            group = _xml_text(dependency, f"{namespace}groupId")
            artifact = _xml_text(dependency, f"{namespace}artifactId")
            version = _resolve_property(_xml_text(dependency, f"{namespace}version"), properties)
            if group and artifact:
                result.append(
                    self._component(f"{group}:{artifact}", version, "maven", relative)
                )
        return result

    def _parse_gradle(self, path: Path, root: Path) -> list[Component]:
        relative = str(path.relative_to(root))
        result: list[Component] = []
        text = path.read_text(encoding="utf-8", errors="ignore")
        for group, artifact, version in re.findall(
            r"['\"]([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([^'\"$\s]+)['\"]", text
        ):
            result.append(self._component(f"{group}:{artifact}", version, "maven", relative))
        spring = re.search(r"id\s*[( ]\s*['\"]org\.springframework\.boot['\"]\s*\)?\s*version\s*['\"]([^'\"]+)", text)
        if spring:
            result.append(self._component("Spring Boot", spring.group(1), "maven", relative))
        return result

    def _parse_csproj(self, path: Path, root: Path) -> list[Component]:
        tree = ET.parse(path)
        relative = str(path.relative_to(root))
        result: list[Component] = []
        for node in tree.getroot().iter():
            if node.tag.split("}")[-1] == "PackageReference":
                name = node.attrib.get("Include") or node.attrib.get("Update")
                version = node.attrib.get("Version")
                if name:
                    result.append(self._component(name, version, "nuget", relative))
            elif node.tag.split("}")[-1] == "TargetFramework" and node.text:
                result.append(
                    Component(".NET", node.text.strip(), "runtime", "runtime", relative,
                              evidence=[f"{relative}:TargetFramework"])
                )
        return result

    def _parse_go_mod(self, path: Path, root: Path) -> list[Component]:
        relative = str(path.relative_to(root))
        result: list[Component] = []
        text = path.read_text(encoding="utf-8")
        go_match = re.search(r"(?m)^go\s+(\S+)", text)
        if go_match:
            result.append(
                Component("Go", go_match.group(1), "runtime", "runtime", relative,
                          evidence=[f"{relative}:go"])
            )
        for name, version in re.findall(r"(?m)^\s*([\w./-]+)\s+(v[0-9][^\s]*)", text):
            result.append(self._component(name, version, "golang", relative))
        return result

    def _parse_containerfile(self, path: Path, root: Path) -> list[Component]:
        relative = str(path.relative_to(root))
        result: list[Component] = []
        for image in re.findall(r"(?im)^\s*FROM\s+(?:--platform=\S+\s+)?([^\s]+)", path.read_text(encoding="utf-8")):
            image = image.split("@")[0]
            name, _, version = image.rpartition(":")
            if not name:
                name, version = version, "latest"
            result.append(
                Component(name, version, "oci", "base-image", relative,
                          evidence=[f"{relative}:FROM {image}"],
                          purl=f"pkg:docker/{name}@{version}")
            )
        return result

    def _scan_source_evidence(self, root: Path) -> list[Component]:
        result: list[Component] = []
        extensions = {".py", ".java", ".kt", ".js", ".jsx", ".ts", ".tsx", ".cs"}
        maximum = int(self.config.get("max_source_files", 5000))
        count = 0
        for path in self._walk(root):
            if path.suffix.lower() not in extensions:
                continue
            count += 1
            if count > maximum:
                self.warnings.append(f"Source evidence scan stopped at {maximum} files.")
                break
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern, (name, category, ecosystem) in SOURCE_PATTERNS:
                if pattern.search(text):
                    relative = str(path.relative_to(root))
                    result.append(
                        Component(name, None, ecosystem, category, "source-evidence",
                                  confidence=0.6, evidence=[relative])
                    )
        return result

    def _component(
        self,
        raw_name: str,
        version: str | None,
        ecosystem: str,
        source: str,
        scope: str = "direct",
    ) -> Component:
        canonical_name, category, canonical_ecosystem = _classify(raw_name, ecosystem)
        purl_name = raw_name.replace(":", "/") if ecosystem == "maven" else raw_name
        purl = f"pkg:{ecosystem}/{purl_name}"
        if version:
            purl += f"@{version}"
        return Component(
            canonical_name,
            version,
            canonical_ecosystem,
            category,
            source,
            scope,
            1.0,
            [source],
            purl,
        )

    def _merge_components(self, components: list[Component]) -> list[Component]:
        merged: dict[tuple[str, str], Component] = {}
        scope_priority = {
            "resolved": 5,
            "resolved-development": 4,
            "direct": 3,
            "development": 2,
            "source-evidence": 1,
        }
        for component in components:
            key = component.key()
            existing = merged.get(key)
            if existing is None:
                merged[key] = component
                continue
            existing.evidence = sorted(set(existing.evidence + component.evidence))
            existing.confidence = max(existing.confidence, component.confidence)
            if component.version and (
                not existing.version
                or scope_priority.get(component.scope, 0) > scope_priority.get(existing.scope, 0)
            ):
                existing.version = component.version
                existing.scope = component.scope
                existing.source = component.source
                existing.purl = component.purl
        return list(merged.values())


def _classify(raw_name: str, ecosystem: str) -> tuple[str, str, str]:
    lowered = raw_name.lower()
    candidates = [lowered, lowered.split(":")[0], lowered.split(":")[-1]]
    for candidate in candidates:
        if candidate in KNOWN_COMPONENTS:
            return KNOWN_COMPONENTS[candidate]
    for key, value in KNOWN_COMPONENTS.items():
        if key in lowered:
            return value
    return raw_name, "library", ecosystem


def _clean_version(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    result = re.sub(r"^[\^~<>=!\s]+", "", result)
    return result or None


def _xml_text(node: ET.Element, tag: str) -> str | None:
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _resolve_property(value: str | None, properties: dict[str, str]) -> str | None:
    if value and value.startswith("${") and value.endswith("}"):
        return properties.get(value[2:-1])
    return value
