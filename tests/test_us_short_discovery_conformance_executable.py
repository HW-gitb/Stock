# -*- coding: utf-8 -*-
"""Slow executable half of the US-short soft-discovery conformance pack.

The static module deliberately keeps the repository-derived helper classes as plain bases so
its normal focused run does not execute mutation-heavy tests.  These TestCase subclasses retain
the original test methods and assertions unchanged while the US-short full discovery pattern
collects this module exactly once.
"""
from __future__ import annotations

import unittest

from tests import test_us_short_discovery_conformance as static_conformance


class K4bExecutableCoverage(static_conformance.K4bExecutableCoverage, unittest.TestCase):
    """Run the unchanged K4b executable coverage assertions only in the executable pack."""


class ExecutableClosureMatrix(static_conformance.ExecutableClosureMatrix, unittest.TestCase):
    """Run the unchanged mutation-heavy closure matrix only in the executable pack."""
