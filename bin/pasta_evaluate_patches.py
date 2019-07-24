"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""
import pickle
import subprocess

from dateutil import parser
from logging import getLogger


_clusters = None
_config = None
_log = getLogger(__name__[-15:])
_repo = None


def build_tag_cache ():
    _log.info('Parsing tags file')

    tags = list()
    patches_by_version = dict()
    try:
        tags_file = open('resources/linux/tags', 'r')
    except FileNotFoundError:
        _log.warning('Could not load tag file')
        raise FileNotFoundError

    for line in tags_file:
        tag = line.split('\t')[0]
        tags.append((tag, parser.parse(line.split('\t')[1][:-1])))
        patches_by_version[tag] = set()

    tags = sorted(tags, key=lambda x: x[1])

    pickle.dump((tags, patches_by_version), open('resources/linux/tags.pkl', 'wb'))
    return tags, patches_by_version


def evaluate_patches(config, prog, argv):
    global _log
    if config.mode != config.Mode.MBOX:
        _log.error('Only works in Mbox mode!')
        return -1

    global _clusters
    global _config
    global _repo

    _, _clusters = config.load_cluster()
    _clusters.optimize()

    _log.info('loading tags…')
    try:
        if 'build_tags' in argv:
            tags, patches_by_version = build_tag_cache()
        else:
            try:
                tags, patches_by_version = pickle.load(open('resources/linux/tags.pkl', 'rb'))
                _log.info('loaded pickle')
            except FileNotFoundError:
                tags, patches_by_version = build_tag_cache()
    except FileNotFoundError:
        return -1

    pass