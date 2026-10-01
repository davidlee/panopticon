"""panopticon-digest: opt-in page digest over the content store (SL-006).

The sole network egress in the package (DEC-002). The pure core — ``gate``,
``config``, ``select``, ``prompt`` — touches no clock, disk or network; the
impure shell wires it to the store and the provider.
"""
