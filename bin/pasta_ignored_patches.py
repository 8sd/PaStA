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
import subprocess
import os

from logging import getLogger
from anytree import LevelOrderIter
from tqdm import tqdm

_config = None
_log = getLogger(__name__[-15:])
_repo = None
_clusters = None
_statistic = {
    'ignored': set(),
    'analyzed patches': set(),
    'ignored patch groups': set(),
    'not ignored patch groups': set(),

    'too old': set(),
    'foreign response': set(),

    'key error': set(),
    'error patch series': set(),
    'key error patch set': set()
}
_patches = None
_threads = None


def patch_is_sent_to_wrong_maintainer(patch):
    affected = _repo[patch].diff.affected
    maintainers = set()

    for file in affected:
        get_maintainer = subprocess.Popen(['perl', 'scripts/get_maintainer.pl', file], cwd='resources/linux/repo/',
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        get_maintainer_out = get_maintainer.communicate()[0]
        maintainers |= set(re.findall(r'<[a-z\.\-]+@[a-z\.\-]+>', get_maintainer_out.decode("utf-8")))
        # Maybe we ought to check if there is one correct maintainer per file?

    print(maintainers)
    print(_repo.mbox.get_messages(patch)[0]['To'])

    for maintainer in maintainers:
        if maintainer not in _repo.mbox.get_messages(patch)[0]['To']:
            return True
    return False


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

<<<<<<< HEAD
    file_name = "ignored_with_subject.tsv"
    f = open(file_name, 'w')
    f.write('MailID' + '\t')
    f.write('Subject' + '\t')
    f.write('From' + '\t')
    f.write('Reference' + '\t')
    f.write('Category' + '\t')
    f.write('Description')
    f.write('\n')
    for patch in tqdm(_statistic['ignored patch groups']):
        email = _repo.mbox.get_messages(patch)[0]
        f.write(patch + '\t')  # MailID
        f.write(email['Subject'].replace('\n', ' ') + '\t')  # Subject
        f.write(email['From'] + '\t')  # From
        f.write('\t')  # Reference
        if 'linux-next' in email['Subject']:  # Category
            f.write('Linux next')
        elif 'git pull' in email['Subject'].lower():
            f.write('Pull Request')
        elif patch_is_sent_to_wrong_maintainer(patch):
            f.write('Wrong Maintainer')
        f.write('\t')
        f.write('')  # Description
        f.write('\n')
    f.close()

    all_authors = set()
    author_ignored = dict()
    author_not_ignored = dict()

    for patch in _patches:
        email = _repo.mbox.get_messages(patch)[0]
        author = email['From'].replace('"', "'")
        if author in all_authors:
            if patch in _statistic['ignored patch groups']:
                author_ignored[author] += 1
            else:
                author_not_ignored[author] += 1
        else:
            all_authors.add(author)
            if patch in _statistic['ignored patch groups']:
                author_ignored[author] = 1
                author_not_ignored[author] = 0
            else:
                author_ignored[author] = 0
                author_not_ignored[author] = 1

    file_name = "authors.tsv"
    f = open(file_name, 'w')
    f.write('From\t')
    f.write('Ignored\t')
    f.write('Not Ignored\t')
    f.write('All\n')
    for author in all_authors:
        f.write(author + '\t')
        f.write(str(author_ignored[author]) + '\t')
        f.write(str(author_not_ignored[author]) + '\t')
        f.write(str(author_ignored[author] + author_not_ignored[author]) + '\n')
    f.close()

    file_name = "all_patches.tsv"
    f = open(file_name, 'w')
    f.write('MailID' + '\t')
    f.write('From' + '\t')
    f.write('Ignored' + '\n')

    for patch in _patches:
        email = _repo.mbox.get_messages(patch)[0]
        f.write(patch.replace('"', "'") + '\t')
        f.write(email['From'].replace('"', "'") + '\t')
        f.write(str(patch in _statistic['ignored patch groups']) + '\n')
    f.close()


def get_author_of_msg(msg):
    email = _repo.mbox.get_messages(msg)[0]
    return email['From']


def patch_has_foreign_response(patch):
    if len(_threads.get_thread(patch).children) == 0:
        return False  # If there is no response the check is trivial

    author = get_author_of_msg(patch)

    for mail in list(LevelOrderIter(_threads.get_thread(patch))):
        this_author = get_author_of_msg(mail.name)
        if this_author is not author:
            return True
    return False


def is_single_patch_ignored(patch):
    try:
        patch_mail = _repo[patch]
    except KeyError:
        _statistic['key error'].add(patch)
        return False

    if _config.time_frame < patch_mail.date.replace(tzinfo=None):
        _statistic['too old'].add(patch)  # Patch is too new to be analyzed
        return False

    if patch_has_foreign_response(patch):
        _statistic['foreign response'].add(patch)
        return False

    _statistic['ignored'].add(patch)
    return True


def get_versions_of_patch(patch):
    return _clusters.get_untagged(patch)


def is_part_of_patch_set(patch):
    try:
        return re.search(r'[0-9]+/[0-9]+\]', _repo[patch].mail_subject) is not None
    except KeyError:
        _statistic['key error patch set'].add(patch)
        return False


def get_patch_set(patch):
    result = set()
    result.add(patch)
    thread = _threads.get_thread(patch)

    if thread.children is None:
        return result

    if not is_part_of_patch_set(patch):
        return result

    # get cover letter
    if thread.name is patch:
        # If first mail of thread is the analyzed patch and the patch is part of the patch set
        # the analyzed patch is the coverletter
        cover = thread
    elif any(patch in child.name for child in thread.children):
        # If the analyzed patch is a child of the first mail in thread the first mail of the thread
        # is the cover letter
        cover = thread
    else:
        # If the cover letter is replied this is a special case I won't check
        # maybe Mete's code can be used to analyze it
        _statistic['error patch series'].add(patch)
        return result
    result.add(cover.name)

    # get leaves of cover letter
    for child in cover.children:
        result.add(child.name)
    return result


def get_related_patches(patch):
    patches = get_versions_of_patch(patch)
    patches |= get_patch_set(patch)
    return patches


def analyze_patch(patch):
    if patch in _statistic['analyzed patches']:
        return

    patches = get_related_patches(patch)

    _statistic['analyzed patches'] |= patches

    for patch in patches:
        ignored = is_single_patch_ignored(patch)
        if ignored is None:
            continue
        if not ignored:
            _statistic['not ignored patch groups'] |= patches
            return

    _statistic['ignored patch groups'] |= patches


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

    _statistic['all patches'] = _clusters.get_untagged()

    _patches = _clusters.get_not_upstream_patches()

    _statistic['upstream patches'] = _statistic['all patches'] - _patches

    _threads = _repo.mbox.load_threads()

    _log.info('Analyzing patches…')
    for patch in tqdm(_patches):
        analyze_patch(patch)

    _statistic['analyzed patches'] = _patches

    write_and_print_statistic()

    return True
