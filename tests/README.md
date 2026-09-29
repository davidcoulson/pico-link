# Pico Link regression tests

This suite checks Pico Link's documented behavior before changes reach users.
It runs the real configuration parser, setup, event handling, and action code
inside a Home Assistant test instance. The Lutron bridge and device services
are replaced with test doubles that record commands. No physical devices are
operated and no running Home Assistant instance is needed.

## Run locally

Use Python 3.14. From the repository root, create and activate a virtual
environment, then install the pinned test dependencies:

```sh
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m pytest -q
```

On Windows, create the environment with `py -3.14 -m venv .venv` and activate it
with `.venv\Scripts\Activate.ps1` in PowerShell. The remaining commands are the
same.

Run the same checks as GitHub:

```sh
python -m ruff check custom_components/pico_link tests
python -m pytest -q --cov=custom_components.pico_link --cov-branch --cov-report=term-missing
```

To focus on one area while developing:

```sh
python -m pytest -q tests/test_gestures.py
```

## Coverage areas

| File | Behavior checked |
| --- | --- |
| `test_light_brightness.py` | Minimum brightness from off, rapid taps with delayed state feedback, upward holds, normal On brightness, and brightness limits |
| `test_configuration.py` | Timing defaults and overrides, normalization, invalid configurations, device-name precedence and ambiguity, entity deduplication, and action placeholders |
| `test_setup_and_events.py` | Full HA setup, invalid and duplicate entries, event filtering, independent remotes, multiple targets, and shutdown cancellation |
| `test_device_controls.py` | On/Off behavior for all three domain-controlling Pico models; shade position/direction, fan speeds/direction, volume limits/mute, and switches |
| `test_gestures.py` | Tap/hold distinctions, release and direction changes, shade stop ordering, natural ramp limits, and concurrent remotes |
| `test_custom_actions.py` | All four scene buttons, middle-button overrides, ordered completion, target/data preservation, service errors, and interrupted sequences |

The new integration tests enter through Home Assistant's setup interface and
send Pico events through its event bus. Assertions check outgoing service
commands and observable errors rather than private implementation details.
Hold tests use real timers with short configured intervals and wait for recorded
commands; they do not replace the hold or ramp logic with a mock. Each test has
a timeout so a stuck gesture fails instead of hanging the entire run.

## Automatic GitHub checks

The `Tests` workflow runs on pushes to `beta` and `main`, and on pull requests
targeting either branch. It installs the same dependencies, runs lint checks,
and runs the suite with a coverage report. Review failures in the repository's
Actions tab before promoting a change. The workflow runs tests only; it does
not deploy updates. The `main` ruleset requires the **Pico Link regression
tests** check from GitHub Actions before a promotion pull request can merge.
See the [promotion workflow](#promoting-beta-to-main).

## Promoting beta to main

Use the two existing branches: develop directly on `beta`, then promote tested
changes to `main` through GitHub. Temporary development branches are optional.

1. Commit and push changes to `beta`.
2. Wait for the **Pico Link regression tests** check to pass and test the
   affected behavior on your Home Assistant hardware.
3. [Open the beta-to-main comparison](https://github.com/smartqasa/pico-link/compare/main...beta)
   and create a pull request, or open the existing promotion pull request.
4. Review the changes and wait for the pull request's required check to pass.
   If GitHub asks you to update the branch, use **Update branch** to bring
   `main` into `beta`, then wait for the checks again.
5. Choose **Create a merge commit** and confirm the merge. Keep `beta` for the
   next development cycle; do not delete it.

The `main` ruleset requires a pull request and the GitHub Actions regression
check against the current base branch. No approving review from another person
is required. Force pushes and deletion are blocked, with no bypass actors.
Direct changes to `beta` remain allowed.

The former `promote.sh` script has been retired. GitHub now provides the
promotion review and merge step. Publishing a versioned GitHub release for
HACS remains a separate operation.

## Adding a regression test

1. Describe the expected behavior independently of the implementation.
2. Add a test that reproduces the problem and fails before the fix.
3. Fix the behavior, then run the focused test and the full suite.
4. Keep the test so later changes can be checked against the same expectation.

For event-driven tests, use the `pico` fixture in `conftest.py`. Configure the
remote with `await pico.setup(...)`, send a tap with `pico.tap(...)`, and assert
the recorded `pico.calls`. During an active hold, wait with
`await pico.next_call()` and send release before calling `await pico.drain()`.
Otherwise draining waits for the active ramp to reach its endpoint.

## Limits

The pinned baseline is Home Assistant 2026.9.1 on Python 3.14. Passing this suite
does not establish compatibility with older HA releases, and does not change
the integration's declared minimum supported version. Add separate version
checks when changing Home Assistant API usage.

Automated checks do not measure Lutron radio reliability, physical light or
shade response, network latency, or whether dimming feels right. Before release,
also test the affected behavior on real hardware. Coverage reports identify
untested paths; a high percentage alone does not prove correct behavior.
