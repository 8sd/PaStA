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

log = getLogger(__name__[-15:])

d_resources = './resources/linux/'
f_suffix = '.pkl'
multithreaded = True

patch_data = None
author_data = None
subsystem_data = None

ignored_related = None
relevant = None
load = None

clustering = None

_repo = None

# TODO: Get list of mailing lists
mailing_lists = [
    'linux-kernel@vger.kernel.org'
]


def get_data_of_patch(args):
    patch = args [0]
    character = args [1]

    global ignored_related
    global relevant
    global load

    try:
        tag = character.linux_version
    except:
        print(character)
        return None

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

    # get all recipients
    recipients = len(character.recipients)
    # distinguish type of recipients
    recipients_lists = 0
    recipients_human = 0
    wrong_maintainer_a = False
    wrong_maintainer_b = True

    for r in character.recipients:
        if r in mailing_lists:
            recipients_lists += 1
        else:
            recipients_human += 1
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
            # TODO break?

    return {
        'id': patch,
        'subject': character.subject,
        'from': character.mail_from[0] + '<' + character.mail_from[1] + '>',
        'from_name': character.mail_from[0],
        'from_mail': character.mail_from[1],
        'kernel version': kv,
        'rcv': rc,
        'upstream': character.is_upstream,
        'ignored': ignored,
        'time': character.date,
        '#recipients': recipients,
        '#recipients_human': recipients_human,
        '#recipients_lists': recipients_lists,
        'maintainers': character.maintainers,
        '#locs': patchobj.diff.lines,
        '#files': len(patchobj.diff.affected),
        '#chunks_in': 0,  # TODO
        '#chunks_out': 0,  # TODO
        'versions of patch': len(cluster),
        'version of patch': len(older) + 1,
        'wrong_maintainer_a': wrong_maintainer_a,
        'wrong_maintainer_b': wrong_maintainer_b,
    }


def build_patch_data():
    global patch_data
    global ignored_related
    global relevant
    global load

    log.info('Loading Data')

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
        pool = Pool(cpu_count())
        results = pool.map(get_data_of_patch, tqdm(load.items()))
    else:
        results = []
        for p in tqdm(load.items()):
            results.add(get_data_of_patch(p))

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
    patch_data['rcv'] = patch_data['rcv'].apply((lambda x: int(x)))
    patch_data['from'] = patch_data['from'].apply((lambda x: [x[0], x[1]]))

    log.info(' … patch data cleaned. ' + str(len(patch_data.index)) + ' patches remain')
    log.info(' → Done')


def enhance_data(config, prog, argv):
    global author_data
    global patch_data
    global subsystem_data
    global clustering
    global _repo

    _repo = config.repo

    _, clustering = config.load_cluster()
    clustering.optimize()

    build_patch_data()

    # clean_data()

    # build_author_data()

    # build_subsystem_data()

    # pickle.dump((author_data, subsystem_data), open(d_resources + 'other_data.pkl', 'wb'))
    patch_data.to_csv('/tmp/patches.csv')

    log.info(' → Done')
