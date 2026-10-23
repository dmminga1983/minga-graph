# Contributing

Thanks for your interest. This project is maintained by its owner, who keeps full control over what is merged.

- **Bug reports and ideas** are welcome as issues. A minimal code sample that reproduces a wrong or missing edge is the most useful thing you can send.
- **Pull requests** may be opened, but every change requires review and approval from the code owner (see `.github/CODEOWNERS`). PRs that add runtime dependencies, network access, telemetry or changes to `.github/` will not be accepted.
- Run the checks locally before opening a PR:

```bash
python -m unittest discover -s tests -v
python -m minga_graph secrets .
```

By contributing you agree that your contribution is licensed under the MIT License.
