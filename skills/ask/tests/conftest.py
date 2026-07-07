def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires RUN_LIVE_PIPELINE=1 and Ollama")