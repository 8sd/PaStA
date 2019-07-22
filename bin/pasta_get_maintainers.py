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
        p = subprocess.Popen(
            ['perl', '../../../tools/get_maintainer.pl', '--subsystem', '--status'],
            cwd=os.path.dirname(os.path.realpath(__file__)) + '/../resources/linux/repo/',
            stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        get_maintainer_pipes = p.communicate(patch_encoded)
    except UnicodeEncodeError:
        try:
            diff = _repo[patch_id].diff
            p = subprocess.Popen(
                ['perl', '../../../tools/get_maintainer.pl', '--subsystem', '--status'] + list(diff.affected),
                cwd=os.path.dirname(os.path.realpath(__file__)) + '/../resources/linux/repo/',
                stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            get_maintainer_pipes = p.communicate()
        except KeyError:
            pass

    get_maintainer_out = get_maintainer_pipes[0].decode("utf-8")
    # parse output
    maintainers = []
    supporter = []
    odd = []
    reviewer = []
    lists = []
    subsystem_or_status = []
    for line in get_maintainer_out.split('\n'):
        if '@' in line:
            if 'maintainer' in line:
                maintainers.append(line)
            elif 'supporter' in line:
                supporter.append(line)
            elif 'list' in line:
                lists.append(line)
            elif 'odd fixer' in line:
                odd.append(line)
            elif 'reviewer' in line:
                reviewer.append(line)
            else:
                _log.warning(line)
        else:
            subsystem_or_status.append(line)

    # run checkpatch
    return (patch_id, {'version': _tag, 'maintainers': maintainers, 'supporter': supporter, 'odd fixer': odd,
                        'reviewer': reviewer, 'lists': lists})


def match_tag_patch (patch_id):
    date_of_mail = parser.parse(_repo.mbox.get_messages(patch_id)[0]['Date'])
    tag_of_patch = ''
    for (tag, timestamp) in _tags:
        if timestamp > date_of_mail:
            break
        tag_of_patch = tag
    return (tag_of_patch, patch_id)


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
    for patch in _patches:
        return_value = match_tag_patch(patch)
        patches_by_version[return_value[0]].add(return_value[1])

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
        for patch_id in patches_by_version[tag]:
            return_value = run_scripts(patch_id)
            result[return_value[0]] = return_value[1]

    # save pkl
    pickle.dump(result, open('maintaiers.pkl', 'wb'))
