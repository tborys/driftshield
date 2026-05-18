"""Corpus of synthetic transcript fixtures used by the recursive-redactor tests.

Each JSON file seeds ``DRIFTSHIELD_REDACTION_CANARY_<token>`` markers at every
nesting depth the shape allows: prompt text, response text, tool input, tool
output, file path, secret-style strings, and user identifier positions.

Synthetic neutral names only. Never include real customer, employer, prospect,
or partner names. Placeholder vocabulary:

* ``ExampleCorp``, ``Acme Workspace``
* ``user@example.test``, ``alice@example.test``
* ``/home/example-user/``
* ``DRIFTSHIELD_REDACTION_CANARY_*``
"""
