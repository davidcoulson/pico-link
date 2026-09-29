# Regression tests

Use Python 3.14 and install the test dependencies in a virtual environment:

```sh
python -m pip install -r requirements-test.txt
python -m pytest -q
```

The tests use Home Assistant 2026.9.1, dispatch Pico events, and record light
service calls. They do not connect to a Lutron bridge or operate physical lights.
This test baseline does not change the integration's minimum supported version.
