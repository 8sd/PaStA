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


_clusters = None
_config = None
_log = getLogger(__name__[-15:])
_p = None
_repo = None
_stats = False

tags = None
patches_by_version = None
subsystems = None
ignored_patches = None
wrong_maintainer = None
process_mails = None
threads = None
upstream = None
patches = None

MAINLINE_REGEX = re.compile(r'^v(\d+\.\d+|2\.6\.\d+)(-rc\d+)?$')

get_maintainers_args = ['perl', '../../../tools/get_maintainer.pl', '--subsystem', '--status', '--separator', ';;']


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


def get_maintainer_file(file):
    if file is '':
        raise FileNotFoundError

    p = subprocess.Popen(get_maintainers_args + [file],
                         cwd=os.path.dirname(os.path.realpath(__file__)) + '/../resources/linux/repo/',
                         stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    get_maintainer_pipes = p.communicate()

    try:
        get_maintainer_out = get_maintainer_pipes[0].decode("utf-8")
        if get_maintainer_out is '':
            error = get_maintainer_pipes[1].decode("utf-8")
            if 'not found' in error:
                file = file[0:file.rfind('/')]
                get_maintainer_out = get_maintainer_file(file)
            elif 'Can\'t open perl script "../../../tools/get_maintainer.pl": No such file or directory' in error:
                _log.warning('Please place get_maintainers.pl in /tools')
                raise ReferenceError('/tools/get_maintainer.pl is missing')
            else:
                raise ValueError('Empty Output, Error: ' + error)
    except UnicodeError:
        error = 'Could not en/decode stuff of file ' + file
        _log.warning(error)
        raise UnicodeError(error)

    return get_maintainer_out


def get_maintainer_patch(patch_id):
    subsystems_with_stati = set()
    maintainers = set()
    supporter = set()
    odd = set()
    reviewer = set()
    lists = set()

    try:
        for file in _repo[patch_id].diff.affected:
            try:
                out = get_maintainer_file(file)
            except:
                return patch_id, None

            lines = out.split('\n')

            for address in lines[0].split(';;'):
                if address is '':
                    continue
                elif 'maintain' in address:
                    maintainers.add(address)
                elif 'supporter' in address:
                    supporter.add(address)
                elif 'list' in address:
                    lists.add(address)
                elif 'odd fixer' in address:
                    odd.add(address)
                elif 'reviewer' in address:
                    reviewer.add(address)

            try:
                stati = lines[1].split(';;')
                subsystems = lines[2].split(';;')
            except IndexError:
                pass

            t = 'THE REST', 'Buried alive in reporters'
            subsystems_with_stati.add(t)
            try:
                subsystems.remove('THE REST')
            except ValueError:
                pass

            try:
                stati.remove('Buried alive in reporters')
            except ValueError:
                pass

            try:
                subsystems.remove('ABI/API')
            except ValueError:
                pass

            for i in range(1, len(subsystems) + 1):
                try:
                    t = subsystems[-i], stati[-i]
                except IndexError:
                    t = subsystems[-i], stati[0]
                subsystems_with_stati.add(t)
    except:
        return patch_id, None

    return patch_id, {'maintainers': maintainers, 'supporter': supporter, 'odd fixer': odd, 'reviewer': reviewer,
                      'lists': lists, 'subsystem': subsystems_with_stati}


def get_maintainers(repo, patches_by_version):
    result = dict()
    for tag in patches_by_version.keys():
        if os.path.isfile('resources/linux/maintainers.' + tag + '.pkl'):
            return_value = pickle.load(open('resources/linux/maintainers.' + tag + '.pkl', 'rb'))
        else:
            if len(patches_by_version[tag]) == 0:
                continue
            # checkout git
            _log.info('Checking out tag: ' + tag)
            repo.repo.checkout('refs/tags/' + tag)

            global _repo
            _repo = repo

            # parallel
            p = get_pool()

            return_value = p.map(get_maintainer_patch, tqdm(patches_by_version[tag]), 10)
            _repo = None

            pickle.dump(return_value,  open('resources/linux/maintainers.' + tag + '.pkl', 'wb'))
        for patch, res in return_value:
            result[patch] = res

    pickle.dump(result, open('resources/linux/maintainers.pkl', 'wb'))
    return result


def get_versions_of_patch(patch):
    return _clusters.get_untagged(patch)


def is_part_of_patch_set(patch):
    try:
        return re.search(r'[0-9]+/[0-9]+\]', _repo[patch].mail_subject) is not None
    except KeyError:
        return False


def get_patch_set(patch):
    global threads

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


def get_related_patches(patch):
    patches = get_versions_of_patch(patch)
    patches |= get_patch_set(patch)
    return patches


def get_author_of_msg(msg):
    email = _repo.mbox.get_messages(msg)[0]
    return email['From']


def patch_has_foreign_response(patch):
    global threads
    thread = threads.get_thread(patch)
    if len(thread.children) == 0:
        return False  # If there is no response the check is trivial

    author = get_author_of_msg(patch)

    for mail in list(LevelOrderIter(thread)):
        this_author = get_author_of_msg(mail.name)
        if this_author is not author:
            return True
    return False


def is_single_patch_ignored(patch):
    global threads
    if patch_has_foreign_response(patch):
        return False, patch

    return True, patch


def get_ignored():
    not_ignored = set()
    not_upstream_patches = _clusters.get_not_upstream_patches()

    p = get_pool()
    results = p.map(is_single_patch_ignored, tqdm(not_upstream_patches))

    for result in results:
        if not result[0]:
            not_ignored |= get_related_patches(result[1])

    ignored = not_upstream_patches - not_ignored

    pickle.dump(ignored, open('resources/linux/ignored.pkl', 'wb'))
    return ignored


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
        _log.warning("Can not check for maintainers, subsystem analysis did not run")

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


def evaluate_patches(config, prog, argv):
    global _log
    if config.mode != config.Mode.MBOX:
        _log.error('Only works in Mbox mode!')
        return -1

    global _clusters
    global _config
    global _stats
    global _repo

    _config = config
    repo = config.repo
    _, _clusters = config.load_cluster()
    _clusters.optimize()

    if 'stats' in argv:
        _stats = True

    global tags
    global patches_by_version
    global subsystems
    global ignored_patches
    global wrong_maintainer
    global process_mails
    global threads
    global upstream
    global patches

    patches = _clusters.get_untagged()
    threads = repo.mbox.load_threads()
    upstream = _clusters.get_upstream_patches()

    mainline_tags = list(filter(lambda x: MAINLINE_REGEX.match(x[0]), repo.tags))

    _log.info('Assigning patches to tags...')
    patches_by_version = dict()
    for patch in patches:
        author_date = repo[patch].author.date
        tag = None
        for cand_tag, cand_tag_date in mainline_tags:
            if cand_tag_date > author_date:
                break
            tag = cand_tag

        if tag is None:
            _log.error('No tag found for patch %s' % patch)
            quit(-1)

        if tag not in patches_by_version:
            patches_by_version[tag] = set()

        patches_by_version[tag].add(patch)

    _log.info('Assigning subsystems to patches')  # ############################################## Subsystem/Maintainer
    if 'no-subsystem' in argv:
        subsystems = None
    elif 'subsystem' in argv or not os.path.isfile('resources/linux/maintainers.pkl'):
        subsystems = get_maintainers(repo, patches_by_version)
    else:
        subsystems = pickle.load(open('resources/linux/maintainers.pkl', 'rb'))

    _log.info('Identify ignored patches')  # ################################################################### Ignored
    if 'no-ignored' in argv:
        ignored_patches = None
    elif 'ignored' in argv or not os.path.isfile('resources/linux/ignored.pkl'):
        ignored_patches = get_ignored()
    else:
        ignored_patches = pickle.load(open('resources/linux/ignored.pkl', 'rb'))

    _log.info('Identify patches sent to wrong maintainers…')  # ####################################### Wrong Maintainer
    if 'no-check-maintainer' in argv:
        wrong_maintainer = None
    elif 'check-maintainer' in argv or not os.path.isfile('resources/linux/check_maintainer.pkl'):
        wrong_maintainer = check_wrong_maintainer()
    else:
        wrong_maintainer = pickle.load(open('resources/linux/check_maintainer.pkl', 'rb'))

    _log.info('Identify process patches (eg. git pull)…')  # ############################################# Process Mails
    if 'no-process-mails' in argv:
        process_mails = None
    elif 'process-mails' in argv or not os.path.isfile('resources/linux/process_mails.pkl'):
        process_mails = identify_process_mails()
    else:
        process_mails = pickle.load(open('resources/linux/process_mails.pkl', 'rb'))

    result = _evaluate_patches()

    write_dict_list(result, 'patch_evaluation.tsv')
    pickle.dump(result, open('patch_evaluation.pkl', 'wb'))

    _log.info("Clean up…")
    p = get_pool()
    p.close()
    p.join()