"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

from pypasta import *
from logging import getLogger

log = getLogger(__name__[-15:])


def get_author_of_msg (msg, repo):
    try:
        return repo[msg].author
    except:
        return None


def get_relevant_subthread(thread, msg):
    subthreads = thread.children
    for subthread in subthreads:
        if subthread.name == msg:
            return subthread
        res = get_relevant_subthread(subthread, msg)
        if res is not None:
            return res
    return None


def patch_has_no_response(thread):
    return len(thread.children) == 0


def patch_was_only_answered_by_author (thread, author, mbox, repo):
    for subthread in thread.children:
        msg = mbox.get_messages(subthread.name)
        if get_author_of_msg(author, repo) is not author and get_author_of_msg(author, repo) is not None:
            return False
        if not patch_was_only_answered_by_author(subthread, author, mbox, repo):
            return False
    return True


def ignored_patches(config, prog, argv):
    if config.mode != config.Mode.MBOX:
        log.error('Only works in Mbox mode!')
        return -1

    found = set()
    mbox = Mbox(config)
    threads = mbox.load_threads()
    repo = config.repo

    # Load patches
    log.info('Loading Patches…')
    cluster = Cluster.from_file("resources/linux/resources/mbox-result")
    cluster.optimize()
    patches = cluster.get_untagged()# Load all patches without commit hash
    log.info('  ↪ ' + str(len(patches)) + 'patches found')
    # Iterate patches
    for patch in patches:
        if patch is None:
            log.info()
            continue
        log.info ('Checking patch ' + patch)
        # check if patch has mail
        thread = threads.get_thread(patch) # Return AnyTree of thread, containing the relevant msg
        relevant_subthread = get_relevant_subthread(thread, patch) # Extract relevant subtree from tree
        if relevant_subthread is None:
            log.warning('No subthread for ' + patch + ' found!')
            continue
        if patch_has_no_response(relevant_subthread):
            found.add(patch)
            continue

        author = get_author_of_msg (patch, repo)
        if patch_was_only_answered_by_author(relevant_subthread, author, mbox, repo):
            found.add(patch)
            continue

    log.info ('  ↪ done')
    # Write to file
    print(len(found))
    for f in found:
        print (f)
    print(len(found))
