"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

_clusters = None
_config = None
_repo = None


def evaluate_patches(config, prog, argv):
    global _clusters
    global _config
    global _repo

    _config = config
    _repo = config.repo

    _, _clusters = config.load_cluster()
    _clusters.opimize()

