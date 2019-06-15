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
    'analyzed patches':set()
}
_patches = None
_threads = None


def write_and_print_statistic():
    log = getLogger('Statistics')
    for key, value in _statistic.items():
        file_name = (datetime.datetime.now().strftime('%Y.%m.%d-%H:%M_') + str(key) + ".out").replace(' ', '_')
        if type(value) is str:
            log.info(str(key) + ': ' + value)
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
    global _clusters
    cluster = _clusters.get_cluster(_clusters.get_key_of_element(patch))
    if cluster is None:
        _statistic['error'].add(patch)
    elif len(cluster) > 1:
        _statistic['large cluster'].add(patch)
        return True
    return False


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
    print(msg)

    email = _repo.mbox.get_messages(msg)[0]

    return email['From']

    #author = _repo[msg].author
    #return author.name + ' ' + author.email


def patch_has_foreign_response(patch):
    if len(_threads.get_thread(patch).children) == 0:
        return False  # If there is no response the check is trivial

    author = get_author_of_msg(patch)

    for mail in list(LevelOrderIter(_threads.get_thread(patch))):
        print(mail)
        this_author = get_author_of_msg(mail.name)
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


def get_patch_set_of_patch(patch):
    return None


def get_versions_of_patch(patch):
    return None


def analyze_patch(patch, ignore_versions=False, ignore_patch_set=False):
    if (not ignore_versions) and has_versions(patch):
        return
#        patches = get_versions_of_patch(patch)
#        for v_patch in patches:
#            analyze_patch(v_patch, True)
#        _patches -= patches
#        return
    if (not ignore_patch_set) and is_part_of_patch_set(patch):
        _statistic['patch set'].add(patch)
        return
#        patches = get_patch_set_of_patch(patch)
#        for p_patch in patches:
#            analyze_patch(p_patch, True, True)
#        _patches -= patches
#        return
    # TODO: Handle version and patch set cases

    is_single_patch_ignored(patch)


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

    # <1515670468-9198-1-git-send-email-abhijeet.kumar@intel.com>

    print(patch_has_foreign_response('<E1ea6ZJ-0003BS-KB@debutante>'))
    quit()

    _log.info('Analyzing patches…')
    for patch in tqdm(_patches):
        analyze_patch(patch)

    write_and_print_statistic()

    return True
