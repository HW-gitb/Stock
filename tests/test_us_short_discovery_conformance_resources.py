# -*- coding: utf-8 -*-
"""The D axis of the US-short conformance pack, in a module of its own.

Its content is unchanged — every derived resource test still runs in BOTH orders
with the repository roots snapshotted after each — but the lane parallelises by
MODULE, so leaving it beside the mutation matrix meant the two slowest checks in
the lane ran back to back on one worker and set the whole lane's wall-clock floor.
Separate modules let them run beside each other instead.
"""
from __future__ import annotations

import unittest

from tests import test_us_short_discovery_conformance as static_conformance


class ResourceIsolationMatrix(static_conformance.ResourceIsolationMatrix, unittest.TestCase):
    """Run the unchanged D resource-isolation assertions on their own worker."""
