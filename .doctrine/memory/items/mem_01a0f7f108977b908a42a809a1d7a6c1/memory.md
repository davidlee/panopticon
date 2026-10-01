# ruff format is not enforced in panopticon

panopticon does not enforce ruff format; never run it repo-wide — format only the files you changed

`just check` runs `lint` (ruff check) and `test` only. Many files are not in
ruff-format layout, deliberately or by history. A repo-wide
`ruff format tests/ panopticon/` once swept 26 unrelated files into an SL-007
commit (493bed4), reverted in 1121e6c.

How to apply: run `ruff format <changed files>` only, or just fix what
`ruff check` reports (E501 etc.) by hand.
