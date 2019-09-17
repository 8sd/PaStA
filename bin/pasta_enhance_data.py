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

log = getLogger(__name__[-15:])

d_resources = './resources/linux/'
f_suffix = '.pkl'

patch_data = None
author_data = None
subsystem_data = None

clustering = None

_repo = None


def build_patch_data():
    global patch_data

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

    data = []
    for patch, character in load.items():
        tag = character.linux_version
        mail = _repo.mbox.get_messages(patch)[0]
        rc = 'rc' in tag

        if rc:
            rc = re.search('-rc[0-9]+', tag).group()[3:]
            kv = re.search('v[0-9]+\.', tag).group() + '%02d' % int(re.search('\.[0-9]+', tag).group()[1:])
        else:
            rc = 0
            kv = re.search('v[0-9]+\.', tag).group() + '%02d' % (
                    int(re.search('\.[0-9]+', tag).group()[1:]) + 1)
        ignored = patch in ignored_related

        data.append({
            'id': patch,
            'subject': mail.subject,
            'from': character.mail_from[0] + character.mail_from[1],
            'from_name': character.mail_from[0],
            'from_mail': character.mail_from[1],
            'kernel version': kv,
            'rcv': rc,
            'upstream': character.is_upstream,
            'ignored': ignored,
            'time': character.date,
        })
    log.info('There are ' + str(len(irrelevants)) + ' irrelevant Mails.')
    patch_data = pd.DataFrame(data)

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

    # build_author_data()

    # build_subsystem_data()

    #pickle.dump((author_data, subsystem_data), open(d_resources + 'other_data.pkl', 'wb'))
    patch_data.to_csv('/tmp/patches.csv')


    log.info(' → Done')
