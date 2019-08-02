"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

import os
import pickle
import re
import subprocess


from anytree import LevelOrderIter
from logging import getLogger
from multiprocessing import Pool, cpu_count
from tqdm import tqdm

from pypasta.LinuxMaintainers import LinuxMaintainers

log = getLogger(__name__[-15:])

_repo = None
_config = None
_p = None
_stats = False

MAINLINE_REGEX = re.compile(r'^v(\d+\.\d+|2\.6\.\d+)(-rc\d+)?$')


def write_cell(file, string):
    string = str(string).replace('\'', '`').replace('"', '`').replace('\n', '|').replace('\t', ' ').replace('=', '-')
    file.write(string + '\t')


def write_dict_list(_list, name):
    f = open(name, 'w')
    for k in _list[0].keys():
        write_cell(f, k)
    f.write('\n')
    for data in _list:
        for k in data.keys():
            write_cell(f, data[k])
        f.write('\n')


def get_pool():
    global _p
    if _p is None:
        _p = Pool(processes=cpu_count(), maxtasksperchild=10)
    return _p


def is_part_of_patch_set(patch):
    try:
        return re.search(r'[0-9]+/[0-9]+\]', _repo[patch].mail_subject) is not None
    except KeyError:
        return False


def get_patch_set(patch):
    result = set()
    result.add(patch)
    thread = threads.get_thread(patch)

    if thread.children is None:
        return result

    if not is_part_of_patch_set(patch):
        return result

    cover = thread  # this only works if
    result.add(cover.name)

    # get leaves of cover letter
    for child in cover.children:
        result.add(child.name)
    return result


def get_author_of_msg(repo, msg_id):
    email = repo.mbox.get_messages(msg_id)[0]
    return email['From'].lower()


def patch_has_foreign_response(repo, patch):
    thread = repo.mbox.threads.get_thread(patch)

    if len(thread.children) == 0:
        return False  # If there is no response the check is trivial

    author = get_author_of_msg(repo, patch)

    for mail in list(LevelOrderIter(thread)):
        this_author = get_author_of_msg(repo, mail.name)
        if this_author != author:
            return True
    return False


def is_single_patch_ignored(patch):
    return patch, not patch_has_foreign_response(_repo, patch)


def get_authors_in_thread(repo, thread):
    authors = set()

    authors.add(get_author_of_msg(repo, thread.name))

    for child in thread.children:
        authors |= get_authors_in_thread(repo, child)

    return authors


def get_ignored(repo, clustering):
    # First, we have to define the term patch. In this analysis, we must only
    # regard patches that either fulfil rule 1 or 2:
    #
    # 1. Patch is the parent of a thread.
    #    This covers classic one-email patches
    #
    # 2. Patch is the 1st level child of the parent of a thread
    #    In this case, the parent can either be a patch (e.g., a series w/o
    #    cover letter) or not a patch (e.g., parent is a cover letter)
    #
    # All other patches MUST be ignored. Rationale: Maintainers may re-send
    # the patch as a reply of the discussion. Such patches must be ignored.
    # Example: Look at the thread of
    #     <20190408072929.952A1441D3B@finisterre.ee.mobilebroadband>

    population_not_accepted = 0
    population_accepted = 0

    not_upstreamed_patches = list()
    for downstream, upstream in clustering.iter_split():
        # Dive into downstream, and check the above-mentioned criteria
        relevant = set()
        for d in downstream:
            thread = repo.mbox.threads.get_thread(d)

            if thread.name == d or \
               d in [x.name for x in thread.children]:
                relevant.add(d)

        # Nothing left? Skip the cluster.
        if len(relevant) == 0:
            continue

        # For the statistics, we'd like to know how many patches fall in this
        # category. Even if they were accepted. No need to continue if the patch
        # was accepted, as it is obvious that it was not ignored. Still, do the
        # housekeeping.
        if len(upstream):
            population_accepted += len(relevant)
            continue

        population_not_accepted += len(relevant)
        not_upstreamed_patches.append(relevant)

    # If a patch was ignored, only the author will appear
    not_ignored = set()
    global _repo
    _repo = repo

    p = Pool(cpu_count())
    not_upstreamed_patches_flattened = {x for cluster in not_upstreamed_patches for x in cluster}
    is_ignored = p.map(is_single_patch_ignored, tqdm(not_upstreamed_patches_flattened))
    p.close()
    p.join()
    _repo = None

    # ignored_patches will be a dictionary key: patch value: is_ignored
    is_ignored = dict(is_ignored)

    num_ignored_patches = len(list(filter(lambda x: x == True, is_ignored.values())))
    log.info('Not accepted patches: %u' % population_not_accepted)
    log.info('Accepted patches: %u' % population_accepted)
    log.info('Found %u ignored patches' % num_ignored_patches)
    log.info('Fraction of ignored patched: %0.3f' %
             (num_ignored_patches /
              (population_accepted + population_not_accepted)))


def check_wrong_maintainer_patch(patch):
    global subsystems
    msgs = _repo.mbox.get_messages(patch)
    if not msgs:
        return False
    msg = msgs[0]
    if not msg:
        return False

    to = msg['To'] if msg['To'] else ''
    cc = msg['Cc'] if msg['Cc'] else ''

    recipients = (to + cc).split(',')
    recipients_clean = []
    for recipient in recipients:
        recipients_clean.append(recipient.replace('\n', '').replace(' ', ''))

    subsystem = subsystems[patch]
    if subsystem is None:
        return None, None

    some = False
    all = True

    for maintainer in subsystem['maintainers']:
        if maintainer in recipients_clean:
            some = True

    for maintainer in subsystem['maintainers'] | subsystem['supporter'] | subsystem['odd fixer'] | subsystem['reviewer']:
        if maintainer not in recipients_clean:
            all = False

    if all:
        return None, None
    if some:
        return None, patch
    return patch, None


def check_wrong_maintainer():
    global patches
    global subsystems

    if subsystems is None:
        log.warning("Can not check for maintainers, subsystem analysis did not run")

    p = get_pool()
    return_value = p.map(check_wrong_maintainer_patch, tqdm(patches))

    min = set()
    max = set()

    for res in return_value:
        min.add(res[0])
        max.add(res[1])

    try:
        min.remove(None)
    except KeyError:
        pass

    try:
        max.remove(None)
    except KeyError:
        pass

    pickle.dump((min, max), open('resources/linux/check_maintainer.pkl', 'wb'))
    return min, max


def is_patch_process_mail(patch):
    try:
        patch_mail = _repo.mbox[patch]
    except KeyError:
        return None
    subject = patch_mail.mail_subject.lower()
    if 'linux-next' in subject:
        return patch
    if 'git pull' in subject:
        return patch
    if 'rfc' in subject:
        return patch
    return None


def identify_process_mails():
    global patches
    p = get_pool()
    result = p.map(is_patch_process_mail, tqdm(patches))

    if result is None:
        return None
    result = set(result)
    try:
        result.remove(None)
    except KeyError:
        pass

    pickle.dump(result, open('resources/linux/process_mails.pkl', 'wb'))
    return result


def evaluate_patch(patch):

    global tags
    global patches_by_version
    global subsystems
    global ignored_patches
    global wrong_maintainer
    global process_mails
    global threads
    global upstream

    email = _repo.mbox.get_messages(patch)[0]
    author = email['From'].replace('\'', '"')
    thread = threads.get_thread(patch)
    mail_traffic = sum(1 for _ in LevelOrderIter(thread))
    first_mail_in_thread = thread.name
    patchobj = _repo[patch]

    to = email['To'] if email['To'] else ''
    cc = email['Cc'] if email['Cc'] else ''

    recipients = to + cc

    for k in patches_by_version.keys():
        if patch in patches_by_version[k]:
            tag = k
    rc = 'rc' in tag

    if rc:
        rcv = re.search('-rc[0-9]+', tag).group()[3:]
        version = re.search('v[0-9]+\.', tag).group() + '%02d' % int(re.search('\.[0-9]+', tag).group()[1:])
    else:
        rcv = 0
        version = re.search('v[0-9]+\.', tag).group() + '%02d' % (
                int(re.search('\.[0-9]+', tag).group()[1:]) + 1)

    subsystem = subsystems[patch]

    return {
        'id': patch,
        'subject': email['Subject'],
        'from': author,
        'ignored': patch in ignored_patches if ignored_patches else None,
        'upstream': patch in upstream,
        'wrong maintainer': patch in wrong_maintainer[0] if wrong_maintainer else None,
        'semi wrong maintainer': patch in wrong_maintainer[1] if wrong_maintainer else None,
        '#LoC': patchobj.diff.lines,
        '#Files': len(patchobj.diff.affected),
        '#recipients without lists': len(re.findall('<', recipients)),
        '#recipients': len(re.findall('@', recipients)),
        'timestamp': patchobj.author.date.timestamp(),
        'after version': tag,
        'rcv': rcv,
        'kernel version': version,
        'maintainers': subsystem['maintainers'] if subsystem else None,
        'helping': (subsystem['supporter'] | subsystem['odd fixer'] | subsystem['reviewer']) if subsystem else None,
        'lists': subsystem['lists'] if subsystem else None,
        'subsystems': subsystem['subsystem'] if subsystem else None,
        'mailTraffic': mail_traffic,
        'firstMailInThread': first_mail_in_thread,
        'process_mail': patch in process_mails if process_mails else None,
    }


def _evaluate_patches():
    p = get_pool()
    result = p.map(evaluate_patch, tqdm(patches))

    return result


def load_maintainers(tag):
    pyrepo = _repo.repo

    tag_hash = pyrepo.lookup_reference('refs/tags/%s' % tag).target
    commit_hash = pyrepo[tag_hash].target
    maintainers_blob_hash = pyrepo[commit_hash].tree['MAINTAINERS'].id
    maintainers = pyrepo[maintainers_blob_hash].data

    try:
        maintainers = maintainers.decode('utf-8')
    except:
        # older versions use ISO8859
        maintainers = maintainers.decode('iso8859')

    m = LinuxMaintainers(maintainers)

    return tag, m


def evaluate_patches(config, prog, argv):
    global _stats

    if config.mode != config.Mode.MBOX:
        log.error('Only works in Mbox mode!')
        return -1


    repo = config.repo
    _, clustering = config.load_cluster()
    clustering.optimize()

    config.load_ccache_mbox()
    repo.mbox.load_threads()

    if 'stats' in argv:
        _stats = True

    global patches_by_version
    global subsystems
    global ignored_patches
    global wrong_maintainer
    global process_mails
    global upstream
    global patches

    log.info('Loading relevant patches...')
    patches = set()
    upstream = set()
    for d, u in clustering.iter_split():
        patches |= d
        upstream |= u

    """
    log.info('Assigning patches to tags...')
    # Only respect mainline versions. No stable versions like v4.2.3
    mainline_tags = list(filter(lambda x: MAINLINE_REGEX.match(x[0]), repo.tags))
    patches_by_version = dict()
    for patch in patches:
        author_date = repo[patch].author.date
        tag = None
        for cand_tag, cand_tag_date in mainline_tags:
            if cand_tag_date > author_date:
                break
            tag = cand_tag

        if tag is None:
            log.error('No tag found for patch %s' % patch)
            quit(-1)

        if tag not in patches_by_version:
            patches_by_version[tag] = set()

        patches_by_version[tag].add(patch)

    log.info('Loading realevant MAINTAINERS files...')
    maintainers_version = dict()
    tags = list(patches_by_version.keys())
    global _repo
    _repo = repo
    p = Pool(processes=cpu_count())
    for tag, maintainers in tqdm(p.imap_unordered(load_maintainers, tags),
                                 total=len(tags), desc='MAINTAINERS'):
        maintainers_version[tag] = maintainers
    p.close()
    p.join()
    _repo = None

    log.info('Assigning subsystems to patches...')
    for tag, patches in patches_by_version.items():
        maintainers = maintainers_version[tag]
        for patch in patches:
            files = repo[patch].diff.affected
            subsystems = maintainers.get_subsystems_by_files(files)
    """

    log.info('Identify ignored patches...')
    get_ignored(repo, clustering)
    """
    if 'no-ignored' in argv:
        ignored_patches = None
    elif 'ignored' in argv or not os.path.isfile('resources/linux/ignored.pkl'):
        ignored_patches = get_ignored(repo, clustering)
    else:
        ignored_patches = pickle.load(open('resources/linux/ignored.pkl', 'rb'))
    """

    log.info('Identify patches sent to wrong maintainers…')  # ####################################### Wrong Maintainer
    if 'no-check-maintainer' in argv:
        wrong_maintainer = None
    elif 'check-maintainer' in argv or not os.path.isfile('resources/linux/check_maintainer.pkl'):
        wrong_maintainer = check_wrong_maintainer()
    else:
        wrong_maintainer = pickle.load(open('resources/linux/check_maintainer.pkl', 'rb'))

    log.info('Identify process patches (eg. git pull)…')  # ############################################# Process Mails
    if 'no-process-mails' in argv:
        process_mails = None
    elif 'process-mails' in argv or not os.path.isfile('resources/linux/process_mails.pkl'):
        process_mails = identify_process_mails()
    else:
        process_mails = pickle.load(open('resources/linux/process_mails.pkl', 'rb'))

    result = _evaluate_patches()

    write_dict_list(result, 'patch_evaluation.tsv')
    pickle.dump(result, open('patch_evaluation.pkl', 'wb'))

    log.info("Clean up…")
    p = get_pool()
    p.close()
    p.join()