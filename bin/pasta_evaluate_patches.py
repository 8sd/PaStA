"""
PaStA - Patch Stack Analysis

Copyright (c) Bayerische Motoren Werke Aktiengesellschaft (BMW AG), 2019
Copyright (c) OTH Regensburg, 2019

Authors:
  Sebastian Duda <sebastian.duda@fau.de>
  Ralf Ramsauer <ralf.ramsauer@oth-regensburg.de>

This work is licensed under the terms of the GNU GPL, version 2. See
the COPYING file in the top-level directory.
"""

import csv
import os
import pickle
import re

from logging import getLogger
from multiprocessing import Pool, cpu_count
from subprocess import call

from tqdm import tqdm

from pypasta.LinuxMaintainers import LinuxMaintainers
from pypasta.LinuxMailCharacteristics import load_linux_mail_characteristics, TAGS, add_or_create, email_get_from

log = getLogger(__name__[-15:])

_repo = None
_config = None
_p = None

MAIL_STRIP_TLD_REGEX = re.compile(r'(.*)\..+')

monitored = [
    'linux-amlogic@lists.infradead.org',
    'linux-arm-kernel@lists.infradead.org',
    'linux-i3c@lists.infradead.org',
    'linux-mtd@lists.infradead.org',
    'linux-riscv@lists.infradead.org',
    'linuxppc-dev@lists.ozlabs.org',
    'cocci@systeme.lip6.fr',
    'linux-block@vger.kernel.org',
    'linux-bluetooth@vger.kernel.org',
    'linux-btrfs@vger.kernel.org',
    'linux-cifs@vger.kernel.org',
    'linux-clk@vger.kernel.org',
    'linux-crypto@vger.kernel.org',
    'linux-ext4@vger.kernel.org',
    'linux-fsdevel@vger.kernel.org',
    'linux-hwmon@vger.kernel.org',
    'linux-iio@vger.kernel.org',
    'linux-integrity@vger.kernel.org',
    'linux-kernel@vger.kernel.org',
    'linux-media@vger.kernel.org',
    'linux-mips@vger.kernel.org',
    'linux-modules@vger.kernel.org',
    'linux-next@vger.kernel.org',
    'linux-nfs@vger.kernel.org',
    'linux-parisc@vger.kernel.org',
    'linux-pci@vger.kernel.org',
    'linux-renesas-soc@vger.kernel.org',
    'linux-rtc@vger.kernel.org',
    'linux-security-module@vger.kernel.org',
    'linux-sgx@vger.kernel.org',
    'linux-trace-devel@vger.kernel.org',
    'linux-watchdog@vger.kernel.org',
    'linux-wireless@vger.kernel.org',
    'netdev@vger.kernel.org	']
maintainers_cache = dict()

stats = dict()

# https://stackoverflow.com/a/28185923
def countNodes(tree):
    count = 1
    for child in tree.children:
        count += countNodes(child)
    return count


def get_most_current_maintainers(subsystem, maintainers):
    if subsystem in maintainers_cache.keys():
        return maintainers_cache[subsystem]
    tags = sorted(maintainers.keys(), reverse=True)
    for tag in tags:
        try:
            maintainers_cache[subsystem] = maintainers[tag].subsystems[subsystem] # TODO return tag
            return maintainers_cache[subsystem]
        except KeyError:
            continue
    raise KeyError('Subsystem ' + subsystem +  'not found')


def get_relevant_patches(characteristics):
    # First, we have to define the term 'relevant patch'. For our analysis, we
    # must only consider patches that either fulfil rule 1 or 2:
    #
    # 1. Patch is the parent of a thread.
    #    This covers classic one-email patches
    #
    # 2. Patch is the 1st level child of the parent of a thread
    #    In this case, the parent can either be a patch (e.g., a series w/o
    #    cover letter) or not a patch (e.g., parent is a cover letter)
    #
    # 3. The patch must not be sent from a bot (e.g., tip-bot)
    #
    # 4. Ignore stable review patches
    #
    # All other patches MUST be ignored. Rationale: Maintainers may re-send
    # the patch as a reply of the discussion. Such patches must be ignored.
    # Example: Look at the thread of
    #     <20190408072929.952A1441D3B@finisterre.ee.mobilebroadband>
    #
    # Furthermore, only consider patches that actually patch Linux (~14% of all
    # patches on Linux MLs patch other projects). Then only consider patches
    # that are not for next, not from bots (there are a lot of bots) and that
    # are no 'process mails' (e.g., pull requests)

    relevant = set()

    all_patches = 0
    skipped_bot = 0
    skipped_stable = 0
    skipped_not_linux = 0
    skipped_no_patch = 0
    skipped_not_first_patch = 0
    skipped_process = 0
    skipped_next = 0

    for m, c in characteristics.items():
        skip = False
        all_patches += 1

        if not c.is_patch:
            skipped_no_patch += 1
            skip = True
        if not c.patches_linux:
            skipped_not_linux += 1
            skip = True
        if not c.is_first_patch_in_thread:
            skipped_not_first_patch += 1
            skip = True

        if c.is_from_bot:
            skipped_bot += 1
            skip = True
        if c.is_stable_review:
            skipped_stable += 1
            skip = True
        if c.process_mail:
            skipped_process += 1
            skip = True
        if c.is_next:
            skipped_next += 1
            skip = True

        if skip:
            continue

        relevant.add(m)

    log.info('')
    log.info('=== Calculation of relevant patches ===')
    log.info('All patches: %u' % all_patches)
    log.info('Skipped patches:')
    log.info('  No patch: %u' % skipped_no_patch)
    log.info('  Not Linux: %u' % skipped_not_linux)
    log.info('  Bot: %u' % skipped_bot)
    log.info('  Stable: %u' % skipped_stable)
    log.info('  Process mail: %u' % skipped_process)
    log.info('  Next: %u' % skipped_next)
    log.info('Relevant patches: %u' % len(relevant))

    return relevant


def get_ignored(characteristics, clustering, relevant):
    # Calculate ignored patches
    ignored_patches = {patch for patch in relevant if
                       not characteristics[patch].is_upstream and
                       not characteristics[patch].has_foreign_response}

    # Calculate ignored patches wrt to other patches in the cluster: A patch is
    # considered as ignored, if all related patches were ignoreed as well
    ignored_patches_related = \
        {patch for patch in ignored_patches if False not in
         [characteristics[x].has_foreign_response == False
          for x in (clustering.get_downstream(patch) & relevant)]}

    num_relevant = len(relevant)
    num_ignored_patches = len(ignored_patches)
    num_ignored_patches_related = len(ignored_patches_related)

    log.info('Found %u ignored patches' % num_ignored_patches)
    log.info('Fraction of ignored patches: %0.3f' %
             (num_ignored_patches / num_relevant))
    log.info('Found %u ignored patches (related)' % num_ignored_patches_related)
    log.info('Fraction of ignored related patches: %0.3f' %
             (num_ignored_patches_related / num_relevant))

    return ignored_patches, ignored_patches_related


def check_correct_maintainer_patch(c):
    # Metric: All lists + at least one maintainer per subsystem
    # needs to be addressed correctly
    # if (not c.mtrs_has_lists or c.mtrs_has_list_per_subsystem) and \
    #   (not c.mtrs_has_maintainers or c.mtrs_has_maintainer_per_subsystem):
    #    return True

    # Metric: At least one correct list + at least one correct maintainer
    # if (not c.mtrs_has_lists or c.mtrs_has_one_correct_list) and \
    #   (not c.mtrs_has_maintainers or c.mtrs_has_one_correct_maintainer):
    #    return True

    # Metric: One correct list + one maintainer per subsystem
    # if (not c.mtrs_has_lists or c.mtrs_has_one_correct_list) and c.mtrs_has_maintainer_per_subsystem:
    #    return True

    # Metric: One correct list
    # if (not c.mtrs_has_lists or has_one_correct_list):
    #    return True

    # Metric: One correct list or one correct maintainer
    if c.mtrs_has_lists and c.mtrs_has_one_correct_list:
        return True
    elif c.mtrs_has_maintainers and c.mtrs_has_one_correct_maintainer:
        return True
    if not c.mtrs_has_lists and not c.mtrs_has_maintainers:
        return c.mtrs_has_linux_kernel

    return False


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


def load_pkl_and_update(filename, update_command):
    ret = None
    if os.path.isfile(filename):
        ret = pickle.load(open(filename, 'rb'))

    ret, changed = update_command(ret)
    if changed:
        pickle.dump(ret, open(filename, 'wb'))

    return ret


def is_subsystem_monitored(m):
    for l in m.list:
        if l not in monitored:
            return False
    return True


def is_subsystem_addressed(patch, m):
    mains = set()
    for mail in m.mail:
        mains.add(mail[1])
    return len(set(patch['recipients'].split(' ')) & (m.list | mains)) is not 0

def load_subsystems(subsystems, tags, patch_data, maintainers):
    for patch in patch_data:
        add_or_create(tags, patch['kv'])
        for subsystem in patch['subsystems']:
            m = get_most_current_maintainers(subsystem, maintainers)
            if not is_subsystem_monitored(m):
                add_or_create(stats, 'subsystem is not monitored')
                continue
            if not is_subsystem_addressed(patch, m):
                add_or_create(stats, 'subsystem is not addressed')
                continue
            # TODO add reference to patch not path itself
            add_or_create(subsystems, subsystem, [patch])
    print('unmonitored: ' + str(stats['subsystem is not monitored']))
    print('unaddressed: ' + str(stats['subsystem is not addressed']))


def dump_subsystems(subsystems, filename, maintainers, tags):
    with open(filename, 'w') as csv_file:
        csv_fields = ['subsystem', 'status', 'extra ml', 'total', 'accepted', 'ignored'] + \
                     sum(map(lambda x: ['total' + x, 'accepted' + x, 'ignored' + x], tags.keys()), [])
        writer = csv.DictWriter(csv_file, fieldnames=csv_fields)
        writer.writeheader()
        for subsystem, patches in subsystems.items():
            subsys = get_most_current_maintainers(subsystem, maintainers)
            status = '; '.join(map(lambda s: s.value, subsys.status))
            extra_ml = subsys.list if len(subsys.list) is 0 else ''

            row = {
                'subsystem': subsystem,
                'status': status,
                'extra ml': extra_ml
            }

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

            for kv, total in count_total.items():
                row['total' + kv] = total
            for kv, accepted in count_accepted.items():
                row['accepted' + kv] = accepted
            for kv, ingored in count_ignored.items():
                row['ignored' + kv] = ingored

            writer.writerow(row)


def dump_characteristics(characteristics, ignored, relevant, filename):
    dump = []
    with open(filename, 'w') as csv_file:
        csv_fields = ['id', 'subject', 'from', 'from_name', 'from_mail', 'recipients', 'recipients_human',
                      'recipients_lists', '#recipients', '#recipients_human', '#recipients_lists', 'subsystems',
                      'lists', 'maintainers', 'reviewers', 'kv', 'rc', 'upstream', 'ignored', 'time', '#locs', '#files',
                      '#chunks_in', '#chunks_out', 'first id in thread', 'is first mail in thread', 'len_thread',
                      'patch series size', 'versions of patch', 'version of patch', 'mtrs_correct'] + TAGS + \
                     ['#' + x for x in TAGS]

        writer = csv.DictWriter(csv_file, fieldnames=csv_fields)
        writer.writeheader()

        for patch in sorted(relevant):
            c = characteristics[patch]

            tag = c.linux_version.split('-rc')
            kv = tag[0]
            rc = 0
            if len(tag) == 2:
                rc = int(tag[1])

            mail_from = c.mail_from[1]

            recipients = ' '.join(sorted(c.recipients))
            recipients_human = c.recipients_human
            recipients_lists = c.recipients_lists

            subsystems = []
            lists = []
            maintainers = []
            reviews = []
            for subsystem, t in c.maintainers.items():
                subsystems.append(subsystem)
                if len(t[0]) is not 0:
                    lists.append(t[0])
                if len(t[1]) is not 0:
                    maintainers.append(t[1])
                if len(t[2]) is not 0:
                    reviews.append(t[2])

            lists = ' '.join(sorted(c.lists))
            mtrs_correct = check_correct_maintainer_patch(c)

            diff_stat = c.diff.diff.diff_stat()

            _res = re.findall('^\[.*[0-9]+\/[0-9]+\]', c.subject)
            if _res:
                patch_series_size = int(re.findall('[0-9]+', _res[0])[-1])
            else:
                patch_series_size = 0

            # extract older versions of the patch
            older = set()
            for p in c.cluster:
                if characteristics[p].date < c.date:
                    older.add(p)

            row = {'id': patch,
                   'subject': c.subject,
                   'from': mail_from,
                   'from_name': c.mail_from[0],
                   'from_mail': c.mail_from[1],
                   'recipients': recipients,
                   'recipients_human': recipients_human,
                   'recipients_lists': recipients_lists,
                   '#recipients': len(c.recipients),
                   '#recipients_human': len(recipients_human),
                   '#recipients_lists': len(recipients_lists),
                   'subsystems': subsystems,
                   'lists': lists,
                   'maintainers': maintainers,
                   'reviewers': reviews,
                   'kv': kv,
                   'rc': rc,
                   'upstream': c.is_upstream,
                   'ignored': patch in ignored,
                   'time': c.date,
                   '#locs': c.diff.diff.lines,
                   '#files': len(c.diff.diff.affected),
                   '#chunks_in': diff_stat[0],
                   '#chunks_out': diff_stat[1],
                   'first id in thread': c.thread.name,
                   'is first mail in thread': c.thread.name == patch,
                   'len_thread': countNodes(c.thread),
                   'patch series size': patch_series_size,
                   'versions of patch': len(c.cluster),
                   'version of patch': len(older) + 1,
                   'mtrs_correct': mtrs_correct}

            for tag in TAGS:
                row[tag] = c.tags[tag]
                row['#' + tag] = len(c.tags[tag])

            dump.append(row)
            writer.writerow(row)
    pickle.dump(dump, open(filename + '.pkl', 'wb'))
    return dump


def load_authors(authors, authors_mail, patch_data, repo):
    for patch in patch_data:
        add_or_create(authors, patch['from'], [patch])

    all_mails = repo.mbox.message_ids(allow_invalid=True)
    for mail_id in all_mails:
        mails = repo.mbox.get_messages(mail_id)
        if len(mails) is 0:
            continue
        author = email_get_from(mails[0])
        add_or_create(authors_mail, author[1])


def dump_authors(authors, authors_mail, filename):
    #with Namsor('resources/namsor.cache') as namsor:
        with open(filename, 'w') as csv_file:
            csv_fields = ['author', 'name', 'mail', 'commit acceptance experience', 'commit experience', '#mails sent',
                          'company', 'tld', 'sex', 'ethnics', 'country']
            writer = csv.DictWriter(csv_file, fieldnames=csv_fields)
            writer.writeheader()

            for author, patches in authors.items():

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
                        company = '.'.join(splits[:-1])[1:]
                        tld = splits[-1]
                except:
                    print('tld, company: ' + patches[0]['from_mail'])

                sex = '' #namsor.get_gender(patches[0]['from_name'])
                ethnics = '' #namsor.get_ethnicity(patches[0]['from_name'])
                country = '' #namsor.get_country(patches[0]['from_name'])

                row = {
                    'author': author,
                    'name': patches[0]['from_name'],
                    'mail': patches[0]['from_mail'],
                    'commit acceptance experience': commit_acceptance_experience,
                    'commit experience': commit_experience,
                    '#mails sent': authors_mail[author],
                    'company': company,
                    'tld': tld,
                    'sex': sex,
                    'ethnics': ethnics,
                    'country': country
                }

                writer.writerow(row)


def load_lists(lists, patch_data, tags):
    for patch in patch_data:
        add_or_create(tags, patch['kv'])
        for list in patch['recipients_lists']:
            add_or_create(lists, list, [patch])


def dump_lists(lists, filename, tags):
    with open(filename, 'w') as csv_file:
        csv_fields = ['list', 'total', 'accepted', 'ignored'] + \
                     sum(map(lambda x: ['total' + x, 'accepted' + x, 'ignored' + x], tags.keys()), [])
        writer = csv.DictWriter(csv_file, fieldnames=csv_fields)
        writer.writeheader()
        for list, patches in lists.items():

            row = {
                'list': list
            }

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

            for kv, total in count_total.items():
                row['total' + kv] = total
            for kv, accepted in count_accepted.items():
                row['accepted' + kv] = accepted
            for kv, ingored in count_ignored.items():
                row['ignored' + kv] = ingored

            writer.writerow(row)


def evaluate_patches(config, prog, argv):
    if config.mode != config.Mode.MBOX:
        log.error('Only works in Mbox mode!')
        return -1

    repo = config.repo
    _, clustering = config.load_cluster()
    clustering.optimize()

    config.load_ccache_mbox()
    repo.mbox.load_threads()

    patches = set()
    upstream = set()
    for d, u in clustering.iter_split():
        patches |= d
        upstream |= u

    all_messages_in_time_window = repo.mbox.message_ids(config.mbox_time_window,
                                                        allow_invalid=True)

    def load_all_maintainers(ret):
        if ret is None:
            ret = dict()

        tags = {x[0] for x in repo.tags if not x[0].startswith('v2.6')}
        tags |= {x[0] for x in repo.tags if x[0].startswith('v2.6.39')}

        # Only load what's not yet cached
        tags -= ret.keys()

        if len(tags) == 0:
            return ret, False

        global _repo
        _repo = repo
        p = Pool(processes=cpu_count())
        for tag, maintainers in tqdm(p.imap_unordered(load_maintainers, tags),
                                     total=len(tags), desc='MAINTAINERS'):
            ret[tag] = maintainers
        p.close()
        p.join()
        _repo = None

        return ret, True

    def load_characteristics(ret):
        if ret is None:
            ret = dict()

        missing = all_messages_in_time_window - ret.keys()
        if len(missing) == 0:
            return ret, False

        missing = load_linux_mail_characteristics(repo,
                                                  missing,
                                                  maintainers_version,
                                                  clustering)

        return {**ret, **missing}, True

    if '--subsystems' in argv or '--load-patches' not in argv:
        log.info('Loading/Updating MAINTAINERS...')
        maintainers_version = load_pkl_and_update(config.f_maintainers_pkl,
                                                  load_all_maintainers)

    if '--load-patches' in argv:
        patch_data = pickle.load(open(config.f_characteristics + '.pkl', 'rb'))
    else:

        log.info('Loading/Updating Linux patch characteristics...')
        characteristics = load_pkl_and_update(config.f_characteristics_pkl,
                                              load_characteristics)

        relevant = get_relevant_patches(characteristics)

        log.info('Identify ignored patches...')
        ignored_patches, ignored_patches_related = get_ignored(characteristics,
                                                               clustering,
                                                               relevant)

        patch_data = dump_characteristics(characteristics, ignored_patches_related, relevant,
                                          config.f_characteristics)

    # TODO Clean
    patch_data_tmp = list()
    for patch in patch_data:
        if patch['from_mail'] == 'baolex.ni@intel.com':
            add_or_create(stats, 'baole')
            continue
        patch_data_tmp.append(patch)
    patch_data = patch_data_tmp
    print('Baole: ' + str(stats['baole']))

    if '--subsystems' in argv:
        log.info('Loading Subsystems...')
        subsystems = dict()
        tags = dict()
        load_subsystems(subsystems, tags, patch_data, maintainers_version)

        filename = config.f_characteristics.split('.')
        filename [-2] += '_subsystem'

        dump_subsystems(subsystems, '.'.join(filename) , maintainers_version, tags)

    if '--authors' in argv:
        log.info('Loading Authors...')
        authors = dict()
        authors_mail = dict()
        load_authors(authors, authors_mail, patch_data, repo)

        filename = config.f_characteristics.split('.')
        filename [-2] += '_authors'

        dump_authors(authors, authors_mail, '.'.join(filename))

    if '--lists' in argv:
        log.info('Loading lists...')
        lists = dict()
        tags = dict()
        load_lists(lists, patch_data, tags)

        filename = config.f_characteristics.split('.')
        filename [-2] += '_lists'

        dump_lists(lists, '.'.join(filename), tags)

    call(['./R/evaluate_patches.R', config.d_rout, config.f_characteristics])
