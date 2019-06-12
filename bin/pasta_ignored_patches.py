"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

import re
import datetime

from logging import getLogger
from anytree import LevelOrderIter
from tqdm import tqdm

_config = None
_log = getLogger(__name__[-15:])
_repo = None
_clusters = None
_statistic = {
    'too old': set(),
    'ignored': set(),
    'error': set(),
    'foreign response': set(),
    'patch set': set(),
    'large cluster': set(),
    'similar patch': set(),
    'analyzed patches': set(),
    'un-ignored patch sets-versions': set(),
    'ignored patch sets-versions': set(),
}
_patches = None
_analyzed_patches = set()
_threads = None


def write_and_print_statistic():
    log = getLogger('Statistics')
    for key, value in _statistic.items():
        file_name = (datetime.datetime.now().strftime('%Y.%m.%d-%H:%M_') + str(key) + ".out").replace(' ', '_')
        if type(value) is str:
            log.info(str(key) + ': ' + str(value))
        elif type(value) is set:
            log.info(str(key) + ': ' + str(len(value)))
            if len(value) < 100000:
                f = open(file_name, 'w')
                for i in value:
                    f.write(str(i) + '\n')
                f.close()
        elif type(value) is dict:
            log.info(str(key) + ': ' + str(len(value)))
            if len(value) < 100000:
                f = open(file_name, 'w')
                for k, v in value.items():
                    f.write(str(k) + '\t' + str(v) + '\n')
                f.close()
        else:
            log.info(str(key) + ': ' + str(value))


def was_similar_patch_merged(patch):
    global _clusters  # TODO: Muss ich nicht via get_tagged() schauen ob etw gemerged ist?
    cluster = _clusters.get_cluster(_clusters.get_key_of_element(patch))
    if cluster is None:
        _statistic['error'].add(patch)
    elif len(cluster) > 1:
        _statistic['large cluster'].add(patch)
        return True
    return False


def is_part_of_patch_set(patch):
    try:
        subject = _repo[patch].mail_subject
    except KeyError:
        return False
    if type(re.search(r'[0-9]+/[0-9]+\]', subject)) is type(None):
        return False
    return True
    # TODO check if patch is part of patch set


def get_author_of_msg(msg):
    try:
        author = _repo[msg].author
    except KeyError:
        return None
    return author.name + ' ' + author.email


def patch_has_foreign_response(patch):
    if len(_threads.get_thread(patch).children) == 0:
        return False  # If there is no response the check is trivial

    author = get_author_of_msg(patch)
    if author is None:
        _log.warning(patch)

    for mail in list(LevelOrderIter(_threads.get_thread(patch))):
        this_author = get_author_of_msg(mail)
        if this_author is None:
            continue
        if this_author is not author:
            return True
    return False


def is_single_patch_ignored(patch):
    try:
        patch_mail = _repo[patch]
    except KeyError:
        _statistic['error'].add(patch)
        return None

    if _config.time_frame < patch_mail.date.replace(tzinfo=None):
        _statistic['too old'].add(patch)  # Patch is too new to be analyzed
        return None

    if patch_has_foreign_response(patch):
        _statistic['foreign response'].add(patch)
        return False

    if was_similar_patch_merged(patch):
        _statistic['similar patch'].add(patch)
        return False
    _statistic['ignored'].add(patch)


def is_mail_cover_letter(patch):  # TODO
    # if mail has no in reply to

    # if mail has >1 children by same author
    author = get_author_of_msg(patch)
    children = _threads.get_thread(patch).children
    mails_by_same_author = 0
    for child in children:
        if author is get_author_of_msg(child):
            mails_by_same_author += 1

    if mails_by_same_author < 2:
        return False
    pass


def _get_patch_set_of_cover_letter(patch):
    children = _threads.get_thread(patch).children
    author = get_author_of_msg(patch)
    result = set()

    for child in children:
        if author is get_author_of_msg(child):
            result.add(child)
    return result


def _get_cover_letter_of_patch_set(patch):  # TODO
    # get thread
    # get node (patch)
    # get parent-node
    return None


def get_patch_set_of_patch(patch):
    if not is_part_of_patch_set(patch):
        return set()

    if is_mail_cover_letter(patch):
        return _get_patch_set_of_cover_letter(patch)
    else:
        return get_patch_set_of_patch(_get_cover_letter_of_patch_set(patch))


def get_versions_of_patch(patch):
    global _clusters
    cluster = _clusters.get_cluster(_clusters.get_key_of_element(patch))

    if cluster is None:
        _statistic['error'].add(patch)
        return set()

    if len(cluster) is 1:
        return set()

    author = get_author_of_msg(patch)
    result = set()
    for patch in cluster:
        if get_author_of_msg(patch) is author:
            result.add(patch)

    return result


def get_versions_and_patch_sets(patch):
    """
    get_versions_and_patch_sets(patch) returns a set of all related patches.

    The function collects all versions and patch sets as long as the result set grows.

    :param patch: base patch
    :return: set of all related patches
    """

    result_set = set()
    current_iteration_set = set()

    current_iteration_set.add(patch)

    while True:
        # Initialize next iteration
        next_iteration_set = set()

        for patch in current_iteration_set:
            if patch in result_set:
                continue  # to improve performance we can skip already analyzed patches

            next_iteration_set |= get_patch_set_of_patch(patch)
            next_iteration_set |= get_versions_of_patch(patch)

        # Clean up
        result_set |= current_iteration_set
        if len(next_iteration_set) is 0:  # no new related patches found aborting analysis
            return result_set
        else:
            current_iteration_set = next_iteration_set


def analyze_patch(patch):
    # Check if patch was already analyzed (e.g. it's part of an analyzed patch set) we can skip it
    global _analyzed_patches
    if patch in _analyzed_patches:
        return

    global _patches

    # Get all related patches (versions, patch sets) of one patch
    # If one related patch is not ignored all related patches count as not ignored
    patches = get_versions_and_patch_sets(patch)

    # Add patches which will be analyzed to analyzed patches set
    # The patches which will be analyzed now cannot be already analyzed because the
    # ↪ 'related'-relation is omnidirectional
    _analyzed_patches |= patches
    for tmp_patch in patches:
        if not is_single_patch_ignored(tmp_patch):
            _statistic['un-ignored patch sets-versions'] |= patches
            return
    _statistic['ignored patch sets-versions'] |= patches


def ignored_patches(config, prog, argv):
    global _log
    if config.mode != config.Mode.MBOX:
        _log.error('Only works in Mbox mode!')
        return -1

    global _config
    global _repo
    global _clusters
    global _statistic
    global _patches
    global _threads

    # Load config and required data
    config.time_frame = config.time_frame.replace(tzinfo=None)
    _config = config

    _repo = config.repo
    f_cluster, _clusters = config.load_patch_groups(must_exist=True)
    _clusters.optimize()

    _statistic['all patches'] = _clusters.get_tagged() | _clusters.get_untagged()
    _statistic['upstream patches'] = _clusters.get_tagged()
    _statistic['analyzed patches'] = _clusters.get_untagged()

    _patches = _clusters.get_untagged()

    _threads = _repo.mbox.load_threads()

    _log.info('Analyzing patches…')
    for patch in tqdm(_patches):
        analyze_patch(patch)

    write_and_print_statistic()

    return
