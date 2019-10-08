"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

from logging import getLogger
import matplotlib.pyplot as plt
import os
import pandas as pd
import pickle
import re
from multiprocessing import cpu_count, Pool
from tqdm import tqdm
import os.path

from pypasta.MailingLists import mailing_lists
from pypasta.LinuxMailCharacteristics import email_get_from
from bin.pasta_evaluate_patches import load_maintainers

log = getLogger(__name__[-15:])

d_resources = './resources/linux/'
f_suffix = '.pkl'
multithreaded = True

patch_data = None
author_data = dict()
subsystem_data = dict()
mails_by_author = dict()
maintainers = None

ignored_related = None
relevant = None
load = None

clustering = None

_repo = None
_threads = None


def add_or_create(d, k, v=1):
    if k in d:
        d[k] += v
    else:
        d[k] = v


# https://stackoverflow.com/a/28185923
def countNodes(tree):
   count = 1
   for child in tree.children:
      count +=  countNodes(child)
   return count


def get_data_of_patch(args):
    patch = args[0]
    character = args[1]

    global ignored_related
    global relevant
    global load

    tag = character.linux_version

    mail = _repo.mbox.get_messages(patch)[0]
    patchobj = _repo[patch]
    rc = 'rc' in tag

    if rc:
        rc = re.search('-rc[0-9]+', tag).group()[3:]
        kv = re.search('v[0-9]+\.', tag).group() + '%02d' % int(re.search('\.[0-9]+', tag).group()[1:])
    else:
        rc = 0
        kv = re.search('v[0-9]+\.', tag).group() + '%02d' % (
                int(re.search('\.[0-9]+', tag).group()[1:]) + 1)
    ignored = patch in ignored_related

    # distinguish type of recipients
    specific_ml = []
    recipients_lists = []
    recipients_human = []
    wrong_maintainer_a = False
    wrong_maintainer_b = True

    for r in character.recipients:
        if r in mailing_lists:
            recipients_lists.append(r)
            if r != "linux-kernel@vger.kernel.org":
                specific_ml.append(r)

        else:
            recipients_human.append(r)

        if r in character.maintainers:
            wrong_maintainer_a = True
        else:
            wrong_maintainer_b = False

    # get all versions of the patch
    cluster = clustering.get_downstream(patch) & relevant

    # extract older versions of the patch
    older = set()
    for p in cluster:
        if load[p].date < character.date:
            older.add(p)

    message = ''
    for line in patchobj.message:
        message += line + '\n'

    signedoffs = []
    for line in patchobj.raw_message:
        if 'signed-off-by' in line.lower():
            signedoffs.append(line[15:])

    diff_stat = patchobj.diff.diff_stat()

    thread = _threads.get_thread(patch)

    len_thread = countNodes(thread)

    subsystems = []
    lists = []
    maintainers = []
    reviews = []
    for subsystem, t in character.maintainers.items():
        subsystems.append(subsystem)
        lists.append(t[0])
        maintainers.append(t[1])
        reviews.append(t[2])

    _res = re.findall('^\[.*[0-9]+\/[0-9]+\]', character.subject)
    if _res:
        patch_series_size = int(re.findall('[0-9]+', _res[0])[-1])
    else:
        patch_series_size = 0

    return {
        'id': patch,
        'subject': character.subject,
        'from': character.mail_from[0] + '<' + character.mail_from[1] + '>',
        'from_name': character.mail_from[0],
        'from_mail': character.mail_from[1],
        'kernel version': kv,
        'rcv': int(rc),
        'upstream': character.is_upstream,
        'ignored': ignored,
        'time': character.date,
        'recipients': character.recipients,
        'recipients_human': recipients_human,
        'recipients_lists': recipients_lists,
        '#recipients': len(character.recipients),
        '#recipients_human': len(recipients_human),
        '#recipients_lists': len(recipients_lists),
        'subsystems': subsystems,
        'lists': lists,
        'maintainers': maintainers,
        'reviewers': reviews,
        '#locs': patchobj.diff.lines,
        '#files': len(patchobj.diff.affected),
        '#chunks_in': diff_stat[0],
        '#chunks_out': diff_stat[1],
        'versions of patch': len(cluster),
        'version of patch': len(older) + 1,
        'wrong_maintainer_a': wrong_maintainer_a,
        'wrong_maintainer_b': wrong_maintainer_b,
        'signed-off-by': signedoffs,
        '#signed-off-by': len(signedoffs),
        'specfic_ml': specific_ml,
        '#specific_ml': len(specific_ml),
        'first id in thread': thread.name,
        'is first mail in thread': thread.name == patch,
        'len_thread': len_thread,
        'patch series size': patch_series_size
    }


def build_patch_data():
    global patch_data
    global ignored_related
    global relevant
    global load

    log.info('Loading patch_data…')
    load = pickle.load(open(d_resources + 'eval_characteristics.pkl', 'rb'))
    ignored_single = set()

    irrelevants = set()
    relevant = set()
    for patch, character in load.items():
        if not character.is_patch or not character.patches_linux or character.is_stable_review or \
                character.is_next or character.process_mail or character.is_from_bot:
            irrelevants.add(patch)
            continue
        relevant.add(patch)

    for patch in irrelevants:
        del load[patch]

    for patch, character in load.items():
        if not (character.is_upstream or character.has_foreign_response):
            ignored_single.add(patch)

    ignored_related = {patch for patch in ignored_single
                       if False not in [load[x].has_foreign_response == False
                                        for x in (clustering.get_downstream(patch) & relevant)]}
    log.info(' … ignored patches done')

    if multithreaded:
        if multithreaded:
            pool = Pool(cpu_count())
            results = pool.map(get_data_of_patch, load.items())
            pool.close()
            pool.join()
    else:
        results = []
        for p in load.items():
            results.append(get_data_of_patch(p))

    log.info(' … patch data built. There are ' + str(len(results)) + ' patches')
    patch_data = pd.DataFrame(results)

    # Clean Data
    # remove v2.* and v5.*
    patch_data.set_index('kernel version', inplace=True)
    patch_data = patch_data.filter(regex='^v[^25].*', axis=0)
    patch_data.reset_index(inplace=True)
    # Bool to int
    patch_data = patch_data.replace(True, 1)
    # rcv as int
    patch_data['from'] = patch_data['from'].apply((lambda x: [x[0], x[1]]))

    log.info(' … patch data cleaned. ' + str(len(patch_data.index)) + ' patches remain')
    log.info(' → Done')


def get_data_of_author(args):
    author = args[0]
    patches = args[1]

    name = patches[0]['from_name']
    mail = patches[0]['from_mail']

    commit_acceptance_experience = 0
    commit_experience = 0
    for patch in patches:
        commit_experience += 1
        if patch['upstream']:
            commit_acceptance_experience += 1

    company = ''
    tld = ''
    try:
        glob = re.findall('@.+', patches[0]['from_mail'])
        if glob:
            splits = glob[0].split('.')
            company = splits [:1][1:]
            tld = splits [-1]
    except:
        print(patches[0]['from_mail'])

    sex = ''
    ethnics = ''
    mails_sent = []

    return {
        'author': author,
        'name': name,
        'mail': mail,
        'commit acceptance experience': commit_acceptance_experience,
        'commit experience': commit_experience,
        'mails sent': mails_sent,
        '#mails sent': len(mails_sent),
        'company': company,
        'tld': tld,
        'sex': sex,
        'ethnics': ethnics
    }


def build_author_data():
    global author_data
    global patch_data
    global mails_by_author

    log.info('Building author_data…')

    mail_ids = _repo.mbox.message_ids(allow_invalid=True)
    for mail_id in mail_ids:
        add_or_create(mails_by_author, email_get_from(mail_id)[1], [mail_id])

    for patch in patch_data.iterrows():
        add_or_create(author_data, patch['from'], [patch])

    if multithreaded:
        pool = Pool(cpu_count())
        results = pool.map(get_data_of_author, tqdm(author_data.items()))
        pool.close()
        pool.join()
    else:
        results = []
        for p in tqdm(author_data.items()):
            results.append(get_data_of_author(p))

    log.info(' … patch data built. There are ' + str(len(results)) + ' authors')
    author_data = pd.DataFrame(results)

    log.info(' → done')


def get_data_of_subsystem(args):
    global maintainers

    subsystem = args[0]
    patches = args[1]

    status = maintainers.subsystems[subsystem]
    extra_ml = False

    count_total = dict()
    count_accepted = dict()
    count_ignored = dict()

    for patch in patches:
        add_or_create(count_total, '')
        add_or_create(count_total, patch['kv'])
        if patch['upstream']:
            add_or_create(count_accepted, '')
            add_or_create(count_accepted, patch['kv'])
        if patch['ignored']:
            add_or_create(count_ignored, '')
            add_or_create(count_ignored, patch['kv'])

    ratios = dict(), dict()
    for kv, total in count_total.items():
        ratios[0][kv] = count_ignored.get(kv, 0) / total
        ratios[1][kv] = count_accepted.get(kv, 0) / total

    res = {
        'subsystem': subsystem,
        'status': status,
        'extra ml': extra_ml
    }
    for kv, ratio in ratios:
        res['ratio ignored/total' + kv] = ratio[0]
        res['ratio accepted/total' + kv] = ratio[1]


def build_subsystem_data():
    global subsystem_data
    global patch_data
    global maintainers

    log.info('Building subsystem_data…')

    maintainers = load_maintainers('v4.20')

    for patch in patch_data.iterrows():
        for subsystem in patch['subsystems']:
            add_or_create(subsystem_data, subsystem, [patch])

    if multithreaded:
        pool = Pool(cpu_count())
        results = pool.map(get_data_of_subsystem, subsystem_data.items())
        pool.close()
        pool.join()
    else:
        results = []
        for p in subsystem_data.items():
            results.append(get_data_of_subsystem(p))

    log.info(' … patch data built. There are ' + str(len(results)) + ' authors')
    subsystem_data = pd.DataFrame(results)

    log.info(' → done')


def enhance_data(config, prog, argv):
    global author_data
    global patch_data
    global subsystem_data
    global clustering
    global _repo
    global _threads

    _repo = config.repo

    _, clustering = config.load_cluster()
    clustering.optimize()

    config.load_ccache_mbox()
    _threads = _repo.mbox.load_threads()

    if os.path.isfile('/tmp/patch.pkl') and False:
        log.info('Load patch.pkl')
        patch_data = pickle.load(open('/tmp/patch.pkl', 'rb'))
    else:
        build_patch_data()
        pickle.dump(patch_data, open('/tmp/patch.pkl', 'wb'))

    if os.path.isfile('/tmp/author.pkl') and False:
        log.info('Load author.pkl')
        author_data = pickle.load(open('/tmp/author.pkl', 'rb'))
    else:
        build_author_data()
        pickle.dump(author_data, open('/tmp/author.pkl', 'wb'))

    if os.path.isfile('/tmp/subsystem.pkl') and False:
        log.info('Load subsystem.pkl')
        subsystem_data = pickle.load(open('/tmp/subsystem.pkl', 'rb'))
    else:
        build_subsystem_data()
        pickle.dump(subsystem_data, open('/tmp/subsystem.pkl', 'wb'))

    # pickle.dump((author_data, subsystem_data), open(d_resources + 'other_data.pkl', 'wb'))
    patch_data.to_csv('/tmp/patches.csv')

    log.info(' → Done')
