# -*- coding: utf-8 -*-
"""The D axis of the US-short conformance pack, in a module of its own.

Every derived resource test runs once in reverse derived order, with the repository
roots snapshotted after the pass. The owning modules cover normal order; this module
keeps the alternate in-process order and root-injection checks on their own worker so
they can run beside the mutation matrix.
"""
from __future__ import annotations

import unittest

from tests import test_us_short_discovery_conformance as static_conformance


class ResourceIsolationMatrix(static_conformance.ResourceIsolationMatrix, unittest.TestCase):
    """Run the D resource-isolation assertions once in reverse order on their own worker."""
