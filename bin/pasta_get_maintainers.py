"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

import datetime
import math
import os
import pickle
import subprocess

from dateutil import parser
from logging import getLogger
from multiprocessing import Pool, cpu_count
from tqdm import tqdm

_repo = ''
_log = getLogger(__name__[-15:])
_tag = ''
_tags = ''

get_maintainers_args = ['perl', '../../../tools/get_maintainer.pl', '--subsystem', '--status', '--separator', ';;']

def patch_date_extractor(patch):
    try:
        return _repo[patch].date
    except KeyError:
        return datetime.datetime.utcnow()

def run_scripts (patch_id):
    patch = _repo.mbox.get_messages(patch_id)[0]._payload
    # run get maintainers
    try:
        patch_encoded = patch.encode('utf-8')
        p = subprocess.Popen(get_maintainers_args,
            cwd=os.path.dirname(os.path.realpath(__file__)) + '/../resources/linux/repo/',
            stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        get_maintainer_pipes = p.communicate(patch_encoded)
    except UnicodeEncodeError:
        try:
            diff = _repo[patch_id].diff
            p = subprocess.Popen(get_maintainers_args + list(diff.affected),
                cwd=os.path.dirname(os.path.realpath(__file__)) + '/../resources/linux/repo/',
                stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            get_maintainer_pipes = p.communicate()
        except KeyError:
            pass

    get_maintainer_out = get_maintainer_pipes[0].decode("utf-8")
    if get_maintainer_out is '':
        error = get_maintainer_pipes[1].decode("utf-8")
        if 'not found' in error:
            return patch_id, None

    # parse output
    maintainers = []
    supporter = []
    odd = []
    reviewer = []
    lists = []
    subsystem_or_status = []
    lines = get_maintainer_out.split('\n')
    for address in lines[0].split(';;'):
        if address is '':
            continue
        elif 'maintain' in address:
            maintainers.append(address)
        elif 'supporter' in address:
            supporter.append(address)
        elif 'list' in address:
            lists.append(address)
        elif 'odd fixer' in address:
            odd.append(address)
        elif 'reviewer' in address:
            reviewer.append(address)

    try:
        stati = lines[1].split(';;')
        subsystems = lines[2].split(';;')
    except:
        print('#####patch_id')
        print(str(patch_id))
        print('#####get_maintainer_out')
        print(str(get_maintainer_out))
        print('#####')
        stati = []
        subsystems = []

    subsystems_with_stati = []

    t = ('THE REST', 'Buried alive in reporters')
    subsystems_with_stati.append(t)
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
        t = ()
        try:
            t = subsystems[-i], stati[-i]
        except IndexError:
            t = subsystems[-i], stati[0]
        subsystems_with_stati.append(t)

    return patch_id, {'version': _tag, 'maintainers': maintainers, 'supporter': supporter, 'odd fixer': odd,
                      'reviewer': reviewer, 'lists': lists, 'subsystem': subsystems_with_stati}


def match_tag_patch(patch_id):
    try:
        date_of_mail = parser.parse(_repo.mbox.get_messages(patch_id)[0]['Date'])
    except:
        date_of_mail = datetime.datetime.now()
    tag_of_patch = ''
    for (tag, timestamp) in _tags:
        if timestamp > date_of_mail:
            break
        tag_of_patch = tag
    return tag_of_patch, patch_id


def get_maintainers(config, prog, argv):
    global _log
    if config.mode != config.Mode.MBOX:
        _log.error('Only works in Mbox mode!')
        return -1

    global _repo
    global _tag
    global _tags

    _config = config

    _repo = config.repo
    f_cluster, _clusters = config.load_cluster(must_exist=True)
    _clusters.optimize()

    _log.info('Loading patches…')
    _patches = _clusters.get_untagged()
    # patches_sorted = sorted(_patches, key=lambda p: patch_date_extractor(p))

    _log.info('Parsing tags file')
    tags = list()
    patches_by_version = dict()
    tags_file = open('resources/linux/tags', 'r')
    for line in tags_file:
        tag = line.split('\t')[0]
        tags.append((tag, parser.parse(line.split('\t')[1][:-1])))

        patches_by_version[tag] = set()

    _tags = sorted(tags, key=lambda x: x[1])

    _log.info('Match patches and tags…')
    # parallel
    p = Pool(processes=cpu_count(), maxtasksperchild=10)
    return_value = p.map(match_tag_patch, tqdm(_patches), 10)
    for tag, result in return_value:
        patches_by_version[tag].add(result)

    result = dict()
    for tag in tags:
        tag = tag[0]
        if len(patches_by_version[tag]) == 0:
            continue
        # checkout git
        _log.info('Checking out tag: ' + tag)
        _repo.repo.checkout('refs/tags/' + tag)
        _tag = tag

        # parallel
        return_value = p.map(run_scripts, tqdm(patches_by_version[tag]), 10)
        for patch, res in return_value:
            result[patch] = res

    # save pkl
    _log.info('Saving pickle…')
    pickle.dump(result, open('maintaiers.pkl', 'wb'))

    _log.info('Cleaning up…')
    p.close()
    p.join()
