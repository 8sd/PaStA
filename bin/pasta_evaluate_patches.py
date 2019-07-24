"""
PaStA - Patch Stack Analysis

Copyright (c) BMW Cat It, 2019

Author:
  Sebastian Duda <sebastian.duda@fau.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""
import datetime
import pickle


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
    p  = get_pool()
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
        raise FileNotFoundError

    for line in tags_file:
        tag = line.split('\t')[0]
        tags.append((tag, parser.parse(line.split('\t')[1][:-1])))
        patches_by_version[tag] = set()

    tags = sorted(tags, key=lambda x: x[1])

    pickle.dump((tags, patches_by_version), open('resources/linux/tags.pkl', 'wb'))
    return tags, patches_by_version


def evaluate_patches(config, prog, argv):
    global _log
    if config.mode != config.Mode.MBOX:
        _log.error('Only works in Mbox mode!')
        return -1

    global _clusters
    global _config
    global _repo

    _, _clusters = config.load_cluster()
    _clusters.optimize()

    _log.info('loading tags…')
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

    _log.info('Loading patches…')
    patches = _clusters.get_untagged()

    _log.info('Assign tags to patches…')
    if 'map_patches_tags' in argv:
        patches_by_version = build_patch_tag_cache(patches_by_version, patches, tags)
    else:
        try:
            patches_by_version = pickle.load(open('resources/linux/tags_patches.pkl', 'rb'))
            _log.info('loaded pickle')
        except FileNotFoundError:
            patches_by_version = build_patch_tag_cache(patches_by_version, patches, tags)

    pass