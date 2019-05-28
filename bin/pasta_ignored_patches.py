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
import datetime

log = getLogger(__name__[-15:])


def get_author_of_msg (msg, repo):
    author = None
    try:
        author = repo[msg].author
    except:
        return None
    return author.name + ' ' + author.email


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


def patch_was_only_answered_by_author (thread, author, repo):
    mbox = repo.mbox
    for subthread in thread.children:
        msg = mbox.get_messages(subthread.name)
        if get_author_of_msg(author, repo) is not author and \
                get_author_of_msg(author, repo) is not None:
            return False
        if not patch_was_only_answered_by_author(subthread, author, repo):
            return False
    return True


def ignored_patches(config, prog, argv):
    if config.mode != config.Mode.MBOX:
        log.error('Only works in Mbox mode!')
        return -1

    # print(config.time_frame)

    # wird alles von load_patch_groups erledigt
    repo = config.repo

    # Load patches
    log.info('Loading Patches…')
    #cluster = Cluster.from_file("resources/linux/resources/mbox-result")
    f_cluster, cluster = config.load_patch_groups(must_exist=True)
    print(f_cluster)

    threads = repo.mbox.load_threads()

    cluster.optimize()
    patches = cluster.get_untagged()# Load all patches without commit hash
    log.info('  ↪ ' + str(len(patches)) + ' patches found')

    found = set()
    notInTimeframe = set()
    responseByOther = set()
    oldest = datetime.datetime.now()
    error = 0
    noResponse = 0


    # Iterate patches
    for patch in patches:
        if patch is None:
            log.info()
            error += 1
            continue
        log.info ('Checking patch ' + patch)
        patchmail = None

        try:
            patchmail = repo[patch]
        except KeyError as e:
            log.warning('Patch ' + patch + 'could not be analyzed')
            log.warnung(e)
            error += 1
            continue

        if oldest.replace(tzinfo=None) > patchmail.date.replace(tzinfo=None):
            oldest = repo[patch].date

        if patchmail.date.replace(tzinfo=None) > config.time_frame.replace(tzinfo=None):
            notInTimeframe.add(patch)
            log.info (repo[patch].date)
            continue

        # check if patch has mail
        thread = threads.get_thread(patch) # Return AnyTree of thread, containing the relevant msg
        relevant_subthread = get_relevant_subthread(thread, patch) # Extract relevant subtree from tree
        if relevant_subthread is None:
            log.warning('No subthread for ' + patch + ' found!')
            error += 1
            continue
        if patch_has_no_response(relevant_subthread):
            found.add(patch)
            noResponse += 1
            continue

        author = get_author_of_msg(patch, repo)
        if patch_was_only_answered_by_author(relevant_subthread, author, repo):
            found.add(patch)
            continue
        responseByOther.add(patch)

    log.info ('  ↪ done')
    # Write to file

    for f in found:
        print (f)
    print("Some stats:")
    print("→ analyzed: " + str(len(patches)))
    print("→ ignored: " + str(len(found)))
    print("→ single mails: " + str(noResponse))
    print("→ not in timeframe: " + str(len(notInTimeframe)))
    print("→ have foreign answer: " + str(len(responseByOther)))
    print("→ oldest patch is from: " + str (oldest))
    print("→ errors during analysis: " + str(error))
