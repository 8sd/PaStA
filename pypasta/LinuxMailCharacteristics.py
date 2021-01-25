"""
PaStA - Patch Stack Analysis

Copyright (c) OTH Regensburg, 2019-2021

Author:
  Ralf Ramsauer <ralf.ramsauer@oth-regensburg.de>
  Sebastian Duda <sebastian@duda.pub>

This work is licensed under the terms of the GNU GPL, version 2.  See
the COPYING file in the top-level directory.
"""
from .MailCharacteristics import MaintainerMetrics, MailCharacteristics, load_mail_characteristics

import re
from logging import getLogger
log = getLogger(__name__[-15:])

_maintainers_version = None


class LinuxMaintainerMetric (MaintainerMetrics):
    def __init__(self, c):
        MaintainerMetrics.__init__(self, c)

        # Metric: All lists + at least one maintainer per section
        # needs to be addressed correctly
        self.all_lists_one_mtr_per_sec = False
        if (not c.mtrs_has_lists or c.mtrs_has_list_per_section) and \
           (not c.mtrs_has_maintainers or c.mtrs_has_maintainer_per_section):
            self.all_lists_one_mtr_per_sec = True

        # Metric: One correct list + one maintainer per section
        self.one_list_mtr_per_sec = False
        if (not c.mtrs_has_lists or c.mtrs_has_one_correct_list) and c.mtrs_has_maintainer_per_section:
            self.one_list_mtr_per_sec = True


class LinuxMailCharacteristics (MailCharacteristics):
    REGEX_COMMIT_UPSTREAM = re.compile('.*commit\s+.+\s+upstream.*', re.DOTALL | re.IGNORECASE)
    REGEX_COVER = re.compile('\[.*patch.*\s0+/.*\].*', re.IGNORECASE)

    def _get_maintainer(self, maintainer, patch):
        sections = maintainer.get_sections_by_files(patch.diff.affected)
        for section in sections:
            s_lists, s_maintainers, s_reviewers = maintainer.get_maintainers(section)
            s_maintainers = {x[1] for x in s_maintainers if x[1]}
            s_reviewers = {x[1] for x in s_reviewers if x[1]}
            self.maintainers[section] = s_lists, s_maintainers, s_reviewers

        self.mtrs_has_lists = False
        self.mtrs_has_maintainers = False
        self.mtrs_has_one_correct_list = False
        self.mtrs_has_one_correct_maintainer = False
        self.mtrs_has_maintainer_per_section = True
        self.mtrs_has_list_per_section = True
        self.mtrs_has_main_list = 'linux-kernel@vger.kernel.org' in self.recipients_lists

        recipients = self.recipients_lists | self.recipients_other | \
                     {self.mail_from[1]}
        recipients = ignore_tlds(recipients)
        for section, (s_lists, s_maintainers, s_reviewers) in self.maintainers.items():
            if section == 'THE REST':
                continue

            s_lists = ignore_tlds(s_lists)
            s_maintainers = ignore_tlds(s_maintainers) | ignore_tlds(s_reviewers)

            if len(s_lists):
                self.mtrs_has_lists = True

            if len(s_maintainers):
                self.mtrs_has_maintainers = True

            if len(s_lists & recipients):
                self.mtrs_has_one_correct_list = True

            if len(s_maintainers & recipients):
                self.mtrs_has_one_correct_maintainer = True

            if len(s_maintainers) and len(s_maintainers & recipients) == 0:
                self.mtrs_has_maintainer_per_section = False

            if len(s_lists) and len(s_lists & recipients) == 0:
                self.mtrs_has_list_per_section = False

        self.maintainer_metrics = MaintainerMetrics(self)

    def _is_stable_review(self, message, patch):
        if 'X-Mailer' in message and \
           'LinuxStableQueue' in message['X-Mailer']:
            return True

        if 'X-stable' in message:
            xstable = message['X-stable'].lower()
            if xstable == 'commit' or xstable == 'review':
                return True

        # The patch needs to be sent to the stable list
        if not ('stable' in self.lists or
                'stable@vger.kernel.org' in self.recipients_lists):
            return False

        message_flattened = '\n'.join(patch.message).lower()

        if 'review patch' in message_flattened:
            return True

        if 'upstream commit' in message_flattened:
            return True

        # Greg uses this if the patch doesn't apply to a stable tree
        if 'the patch below does not apply to the' in message_flattened:
            return True

        if MailCharacteristics.REGEX_COMMIT_UPSTREAM.match(message_flattened):
            return True

        return False

    def _is_next(self): # Linuxspecific?
        if 'linux-next' in self.lists:
            return True

        if 'linux-next@vger.kernel.org' in self.recipients_lists:
            return True

        return False



def _load_linux_mail_characteristic(message_id):
    return message_id, MailCharacteristics(_repo, _maintainers_version,
                                                _clustering, message_id)

def load_linux_mail_characteristics(config, maintainers_version, clustering,
                                    ids):
    repo = config.repo

    BOTS = config.bots
    POTENTIAL_BOTS = config.potential_bot
    BOTS_REGEX = config.bots_regex
    PROCESSES = config.processes
    global _maintainers_version
    _maintainers_version = maintainers_version
    characteristics = load_mail_characteristics(config, clustering,
                                    ids, _load_linux_mail_characteristic)

    _maintainers_version = None
    return characteristics
