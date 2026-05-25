"""Pulpo test package.

This file exists to shadow an unrelated ``tests`` package that ships in
some anaconda Python installations at
``site-packages/tests/``. Without this empty marker, an
``import tests.newsletter…`` in a Python that has anaconda's ``tests``
on sys.path resolves to the anaconda one and fails with
``ModuleNotFoundError: No module named 'tests.newsletter'`` — bit
Sebas's local dev env (#469-style failure).

CI's ubuntu-latest image doesn't have the conflicting package, so the
test suite passes there with or without this file. The file is a
cheap, safe, local-friendly fix.
"""
