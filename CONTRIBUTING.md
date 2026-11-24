# Contributing to OpenSees Studio

OpenSees Studio is a source-available, noncommercial project. Contributions
that improve the application, documentation, tests, and OpenSees integration
are welcome.

## License of contributions

By submitting a contribution, you confirm that:

- you wrote the contribution or have the right to submit it, and
- you license it to the project and its users under the **PolyForm
  Noncommercial License 1.0.0**, the same license as the project.

Do not submit code copied from a project whose license is incompatible with
this project.

## Developer Certificate of Origin

Sign off your commits to confirm the contribution:

```text
git commit -s -m "Describe the change"
```

The sign-off adds a `Signed-off-by:` line. This is a lightweight
Developer Certificate of Origin (DCO), not a copyright assignment.

## Third-party code

- Do not add dependencies that require commercial royalties or incompatible
  distribution terms.
- Do not add GPL-only Qt modules to the desktop build.
- Keep OpenSees, OpenSeesPy, Qt/PySide6, and other third-party notices up to
  date when dependencies change.

## Practical checks

Run the relevant tests before opening a pull request:

```text
python tests/test_solver.py
python tests/test_gui.py
python tests/test_mcp.py
python tests/test_analysis_runner.py
```
