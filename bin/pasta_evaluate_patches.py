"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""
import datetime
import os
import pickle
import re
import subprocess


from anytree import LevelOrderIter
from dateutil import parser
from functools import partial
from logging import getLogger
from multiprocessing import Pool, cpu_count
from tqdm import tqdm


_clusters = None
_config = None
_log = getLogger(__name__[-15:])
_p = None
_repo = None
_stats = False

_analyzed_patches = set()


get_maintainers_args = ['perl', '../../../tools/get_maintainer.pl', '--subsystem', '--status', '--separator', ';;']


def get_pool():
    global _p
    if _p is None:
        _p = Pool(processes=cpu_count(), maxtasksperchild=10)
    return _p


def match_tag_patch(tags, patch_id):
    try:
        date_of_mail = parser.parse(_repo.mbox.get_messages(patch_id)[0]['Date'])
    except:
        date_of_mail = datetime.datetime.utcnow()
    tag_of_patch = ''
    for (tag, timestamp) in tags:
        try:
            if timestamp > date_of_mail:
                break
        except:
            if timestamp.replace(tzinfo=None) > date_of_mail.replace(tzinfo=None):
                break
        tag_of_patch = tag
    return tag_of_patch, patch_id


def build_patch_tag_cache (patches_by_version, patches, tags):
    p = get_pool()
    f = partial(match_tag_patch, tags)
    return_value = p.map(match_tag_patch, tqdm(patches), 10)
    for tag, result in return_value:
        patches_by_version[tag].add(result)

    pickle.dump(patches_by_version, open('resources/linux/tags_patches.pkl', 'wb'))
    return patches_by_version


def build_tag_cache ():
    _log.info('Parsing tags file')

    tags = list()
    patches_by_version = dict()
    try:
        tags_file = open('resources/linux/tags', 'r')
    except FileNotFoundError:
        _log.warning('Could not load tag file')
        raise FileNotFoundError('resources/linux/tags')

    for line in tags_file:
        tag = line.split('\t')[0]
        tags.append((tag, parser.parse(line.split('\t')[1][:-1])))
        patches_by_version[tag] = set()

    tags = sorted(tags, key=lambda x: x[1])

    pickle.dump((tags, patches_by_version), open('resources/linux/tags.pkl', 'wb'))
    return tags, patches_by_version


def get_maintainer_file(file):
    if file is '':
        raise FileNotFoundError

    p = subprocess.Popen(get_maintainers_args + [file],
                         cwd=os.path.dirname(os.path.realpath(__file__)) + '/../resources/linux/repo/',
                         stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    get_maintainer_pipes = p.communicate()

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
    return get_maintainer_out


def get_maintainer_patch(patch_id):
    subsystems_with_stati = set()
    maintainers = set()
    supporter = set()
    odd = set()
    reviewer = set()
    lists = set()

    for file in _repo[patch_id].diff.affected:
        try:
            out = get_maintainer_file(file)
        except FileNotFoundError:
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

        if len(subsystems) is not 0 and len(stati) is not 0:
            for i in range(1, len(subsystems) + 1):
                t = ()
                try:
                    t = subsystems[-i], stati[-i]
                except IndexError:
                    t = subsystems[-i], stati[0]
                subsystems_with_stati.add(t)

    return patch_id, {'maintainers': maintainers, 'supporter': supporter, 'odd fixer': odd, 'reviewer': reviewer,
                      'lists': lists, 'subsystem': subsystems_with_stati}


def get_maintainers (patches_by_version):
    result = dict()
    for tag in patches_by_version.keys():
        try:
            return_value = pickle.load(open('resources/linux/maintainers.' + tag + '.pkl', 'rb'))
        except FileNotFoundError:
            if len(patches_by_version[tag]) == 0:
                continue
            # checkout git
            _log.info('Checking out tag: ' + tag)
            _repo.repo.checkout('refs/tags/' + tag)

            # parallel
            p = get_pool()
            return_value = p.map(get_maintainer_patch, tqdm(patches_by_version[tag]), 10)
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


def get_patch_set(threads, patch):
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


def get_related_patches(threads, patch):
    patches = get_versions_of_patch(patch)
    patches |= get_patch_set(threads, patch)
    return patches


def get_author_of_msg(msg):
    email = _repo.mbox.get_messages(msg)[0]
    return email['From']


def patch_has_foreign_response(threads, patch):
    thread = threads.get_thread(patch)
    if len(thread.children) == 0:
        return False  # If there is no response the check is trivial

    author = get_author_of_msg(patch)

    for mail in list(LevelOrderIter(thread)):
        this_author = get_author_of_msg(mail.name)
        if this_author is not author:
            return True
    return False


def is_single_patch_ignored(threads, patch):
    if patch_has_foreign_response(threads, patch):
        return False, patch

    return True, patch


def get_ignored(threads):
    not_ignored = set()
    not_upstream_patches = _clusters.get_not_upstream_patches()

    p = get_pool()
    f = partial(is_single_patch_ignored, threads)
    results = p.map(f, tqdm(not_upstream_patches))

    #results = []
    #for patch in tqdm(not_upstream_patches):
    #    results.append(is_patch_ignored(threads, patch))

    for result in results:
        if not result[0]:
            not_ignored |= get_related_patches(result[1])

    ignored = not_upstream_patches - not_ignored

    pickle.dump(ignored, open('resources/linux/ignored.pkl', 'wb'))
    return ignored


def check_wrong_maintainer_patch(subsystems, patch):
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

    min = False
    max = True

    for maintainer in subsystem['maintainers']:
        if maintainer in recipients_clean:
            min = True

    for maintainer in subsystem['maintainers'] | subsystem['supporter'] | subsystem['odd fixer'] | subsystem['reviewer']:
        if maintainer not in recipients_clean:
            max = False

    if max:
        return None, None
    if min:
        return None, patch
    return patch, None


def check_wrong_maintainer(patches, subsystems):
    p = get_pool()
    f = partial(check_wrong_maintainer_patch,subsystems)
    return_value = p.map(f, patches)

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


def identify_process_mails(patches):
    p = get_pool()
    result = p.map(is_patch_process_mail, patches)

    if result is None:
        return None
    result = set(result)
    try:
        result.remove(None)
    except KeyError:
        pass

    pickle.dump(result, open('resources/linux/process_mails.pkl', 'wb'))
    return result


def evaluate_patches(config, prog, argv):
    global _log
    if config.mode != config.Mode.MBOX:
        _log.error('Only works in Mbox mode!')
        return -1

    global _clusters
    global _config
    global _repo
    global _stats

    _config = config
    _repo = config.repo
    _, _clusters = config.load_cluster()
    _clusters.optimize()

    if 'stats' in argv:
        _stats = True

    _log.info('loading tags…')  ################################################################################### Tags
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

    _log.info('Loading patches…')  ############################################################################# Patches
    patches = _clusters.get_untagged()

    _log.info('Assign tags to patches…')  ################################################################# Tag ←→ Patch
    if 'map_patches_tags' in argv:
        patches_by_version = build_patch_tag_cache(patches_by_version, patches, tags)
    else:
        try:
            patches_by_version = pickle.load(open('resources/linux/tags_patches.pkl', 'rb'))
            _log.info('loaded pickle')
        except FileNotFoundError:
            patches_by_version = build_patch_tag_cache(patches_by_version, patches, tags)

    _log.info('Assigning susbsystems to patches')  ################################################ Subsystem/Maintainer
    if 'subsystem' in argv:
        subsystems = get_maintainers(patches_by_version)
    elif 'no-subsystem' in argv:
        subsystems = None
    else:
        try:
            subsystems = pickle.load(open('resources/linux/maintainers.pkl', 'rb'))
        except FileNotFoundError:
            subsystems = get_maintainers(patches_by_version)

    threads = _repo.mbox.load_threads()

    _log.info('Identify ignored patches')  ##################################################################### Ignored
    if 'ignored' in argv:
        ignored_patches = get_ignored(threads)
    elif 'no-ignored' in argv:
        ignored_patches = None
    else:
        try:
            ignored_patches = pickle.load(open('resources/linux/ignored.pkl', 'rb'))
        except FileNotFoundError:
            ignored_patches = get_ignored(threads)

    _log.info('Identify patches sent to wrong maintainers…')  ######################################### Wrong Maintainer
    if 'no-check-maintainer' in argv:
        wrong_maintainer = None
    elif 'check-maintainer' in argv or not os.path.isfile('resources/linux/check_maintainer.pkl'):
        wrong_maintainer = check_wrong_maintainer(patches, subsystems)
    else:
        wrong_maintainer = pickle.load(open('resources/linux/check_maintainer.pkl', 'rb'))

    _log.info('Identify process patches (eg. git pull)…')  ############################################### Process Mails
    if 'no-process-mails' in argv:
        process_mails = None
    elif 'process-mails' in argv or not os.path.isfile('resources/linux/process_mails.pkl'):
        process_mails = identify_process_mails(patches)
    else:
        process_mails = pickle.load(open('resources/linux/process_mails.pkl', 'rb'))

    pass

    for mail in process_mails:
        print(_repo.mbox[mail].subject)

    _log.info("Clean up…")
    p = get_pool()
    p.close()
    p.join()