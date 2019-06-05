"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

import re

from logging import getLogger
from anytree import LevelOrderIter
from tqdm import tqdm

_config = None
_log = getLogger(__name__[-15:])
_repo = None
_statistic = {
    'too old': set(),
    'ignored': set(),
    'error': set(),
    'foreign response': set(),
    'patch set': set()
}
_patches = None
_threads = None


def print_statistic():
    log = getLogger('Statistics')
    for key, value in _statistic.items():
        if type(value) is str:
            log.info(str(key) + ': ' + value)
        elif type(value) is set:
            log.info(str(key) + ': ' + str(len(value)))
        elif type(value) is dict:
            log.info(str(key) + ': ' + str(len(value)))
        else:
            log.info(str(key) + ': ' + str(value))


def analyze_patch_set():
    return  # TODO iterate over all patches from patch set


def is_part_of_patch_set(patch):
    try:
        subject = _repo[patch].mail_subject
    except KeyError:
        return False
    if type(re.search(r'[0-9]+\/[0-9]+\]', subject)) is type(None):
        return False
    return True
    # TODO check if patch is part of patch set


def has_versions(patch):
    return False  # TODO check if entity (patch, patch set) has versions


def get_author_of_msg (msg):
    try:
        author = _repo[msg].author
    except KeyError:
        return None
    return author.name + ' ' + author.email


def patch_has_foreign_response(patch):
    try:
        author = get_author_of_msg(patch)
    except KeyError:
        _statistic['error'] = patch
        return False

    for mail in list(LevelOrderIter(_threads.get_thread(patch))):
        try:
            if not get_author_of_msg(mail) is author:
                return True
        except KeyError:
            _statistic['error'].add(mail)
    return False


def patch_has_response(patch):
    return len(_threads.get_thread(patch).children) == 0


def is_single_patch_ignored(patch):
    try:
        patch_mail = _repo[patch]
    except KeyError:
        _statistic['error'].add(patch)
        return None

    if _config.time_frame < patch_mail.date.replace(tzinfo=None):
        _statistic['too old'].add(patch)  # Patch is too new to be analyzed
        return None

    if patch_has_response(patch):
        if patch_has_foreign_response(patch):
            _statistic['foreign response'].add(patch)
        else:
            _statistic['ignored'].add(patch)
    else:
        _statistic['ignored'].add(patch)


def analyze_patch(patch, patches, ignore_versions=False, ignore_patch_set=False):
    if (not ignore_versions) and has_versions(patch):
        return  # TODO: Analyze all versions
    if (not ignore_patch_set) and is_part_of_patch_set(patch):
        _statistic['patch set'].add(patch)
        return  # TODO: Analyze all patches of patch set
    # TODO: Handle version and patch set cases
    is_single_patch_ignored(patch)


def ignored_patches(config, prog, argv):
    global _log
    if config.mode != config.Mode.MBOX:
        _log.error('Only works in Mbox mode!')
        return -1

    global _config
    global _repo
    global _statistic
    global _patches
    global _threads

    config.time_frame = config.time_frame.replace(tzinfo=None)
    _config = config

    _repo = config.repo
    f_cluster, cluster = config.load_patch_groups(must_exist=True)
    cluster.optimize()

    _statistic['all patches'] = cluster.get_tagged() | cluster.get_untagged()
    _statistic['upstream patches'] = cluster.get_tagged()

    _patches = cluster.get_untagged()

    _threads = _repo.mbox.load_threads()

    _log.info("Analyzing patches…")
    for patch in tqdm(_patches):
        analyze_patch(patch, _patches)

    print_statistic()

    return True
