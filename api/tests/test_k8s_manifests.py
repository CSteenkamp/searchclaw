"""Tests for Kubernetes manifest validity."""

import os
from pathlib import Path

import pytest
import yaml


K8S_BASE = Path(__file__).resolve().parent.parent.parent / "k8s"


def _load_all_yaml_docs(path: Path) -> list[dict]:
    """Load all YAML documents from a file."""
    docs = []
    with open(path) as f:
        for doc in yaml.safe_load_all(f.read()):
            if doc:
                docs.append(doc)
    return docs


def _find_yaml_files(directory: Path) -> list[Path]:
    """Recursively find all YAML files."""
    files = []
    for ext in ("*.yml", "*.yaml"):
        files.extend(directory.rglob(ext))
    return sorted(files)


class TestK8sManifests:
    """Kubernetes manifest validation."""

    def test_yaml_files_exist(self):
        """K8s directory contains YAML files."""
        files = _find_yaml_files(K8S_BASE)
        assert len(files) > 0, "No YAML files found in k8s/"

    @pytest.mark.parametrize("yaml_file", _find_yaml_files(K8S_BASE), ids=lambda p: str(p.relative_to(K8S_BASE)))
    def test_yaml_valid(self, yaml_file: Path):
        """All YAML files are valid."""
        docs = _load_all_yaml_docs(yaml_file)
        assert len(docs) > 0, f"{yaml_file} contains no valid YAML documents"

    def test_namespace_exists(self):
        """Namespace manifest exists and sets searchclaw."""
        ns_file = K8S_BASE / "base" / "namespace.yml"
        assert ns_file.exists(), "namespace.yml not found"
        docs = _load_all_yaml_docs(ns_file)
        ns = docs[0]
        assert ns["kind"] == "Namespace"
        assert ns["metadata"]["name"] == "searchclaw"

    def test_api_deployment_has_required_fields(self):
        """API deployment has required fields."""
        dep_file = K8S_BASE / "base" / "api-gateway" / "deployment.yml"
        assert dep_file.exists()
        docs = _load_all_yaml_docs(dep_file)
        dep = docs[0]
        assert dep["kind"] == "Deployment"
        assert dep["spec"]["replicas"] >= 1
        containers = dep["spec"]["template"]["spec"]["containers"]
        assert len(containers) > 0
        container = containers[0]
        assert "resources" in container
        assert "requests" in container["resources"]
        assert "limits" in container["resources"]

    def test_worker_deployment_exists(self):
        """Worker deployment exists with resource limits."""
        dep_file = K8S_BASE / "base" / "worker" / "deployment.yml"
        assert dep_file.exists(), "worker deployment not found"
        docs = _load_all_yaml_docs(dep_file)
        dep = docs[0]
        assert dep["kind"] == "Deployment"
        containers = dep["spec"]["template"]["spec"]["containers"]
        container = containers[0]
        assert "resources" in container
        # Workers need higher memory for browser rendering
        mem_limit = container["resources"]["limits"]["memory"]
        assert mem_limit is not None

    def test_redis_statefulset(self):
        """Redis statefulset has PVC."""
        ss_file = K8S_BASE / "base" / "redis" / "statefulset.yml"
        assert ss_file.exists()
        docs = _load_all_yaml_docs(ss_file)
        ss = [d for d in docs if d["kind"] == "StatefulSet"][0]
        assert "volumeClaimTemplates" in ss["spec"]

    def test_postgres_statefulset(self):
        """PostgreSQL statefulset has PVC."""
        ss_file = K8S_BASE / "base" / "postgres" / "statefulset.yml"
        assert ss_file.exists()
        docs = _load_all_yaml_docs(ss_file)
        ss = [d for d in docs if d["kind"] == "StatefulSet"][0]
        assert "volumeClaimTemplates" in ss["spec"]

    def test_kustomization_includes_worker(self):
        """Kustomization references worker deployment."""
        kust_file = K8S_BASE / "base" / "kustomization.yaml"
        assert kust_file.exists()
        docs = _load_all_yaml_docs(kust_file)
        kust = docs[0]
        assert "worker/deployment.yml" in kust["resources"]

    def test_staging_overlay(self):
        """Staging overlay exists and references base."""
        kust_file = K8S_BASE / "overlays" / "staging" / "kustomization.yaml"
        assert kust_file.exists()
        docs = _load_all_yaml_docs(kust_file)
        kust = docs[0]
        assert "../../base" in kust["resources"]

    def test_production_overlay(self):
        """Production overlay exists and references base."""
        kust_file = K8S_BASE / "overlays" / "production" / "kustomization.yaml"
        assert kust_file.exists()
        docs = _load_all_yaml_docs(kust_file)
        kust = docs[0]
        assert "../../base" in kust["resources"]
