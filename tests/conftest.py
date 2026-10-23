import pytest

from backend.simulator.generator import generate, list_scenarios, load_scenario


@pytest.fixture(scope="session")
def matches():
    """Every scenario generated once per test session (about 3 s each)."""
    return {sid: generate(load_scenario(sid)) for sid in list_scenarios()}


@pytest.fixture(scope="session")
def derby(matches):
    return matches["derby_balanced"]
