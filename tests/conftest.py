"""Pytest configuration and shared fixtures for JobPilot test suite."""


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that hit live APIs (Gemini, Playwright, etc.)",
    )
    parser.addoption(
        "--save-fixtures",
        action="store_true",
        default=False,
        help="Save live API responses as fixture files (use with --run-integration)",
    )
