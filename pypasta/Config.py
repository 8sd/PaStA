"""
PaStA - Patch Stack Analysis

Copyright (c) OTH Regensburg, 2016-2019

Author:
  Ralf Ramsauer <ralf.ramsauer@oth-regensburg.de>

This work is licensed under the terms of the GNU GPL, version 2.  See
the COPYING file in the top-level directory.
"""

import pygit2
import toml

from enum import Enum
from os.path import join, realpath, isfile, isdir, isabs
from os import makedirs
from logging import getLogger

from .Cluster import Cluster
from .Repository import Repository
from .PatchStack import PatchStackDefinition
from .Util import load_commit_hashes, persist_commit_hashes, parse_date_ymd

log = getLogger(__name__[-15:])


class Thresholds:
    def __init__(self, autoaccept, interactive, diff_lines_ratio,
                 heading, filename, message_diff_weight,
                 author_date_interval):
        """
        :param autoaccept: Auto accept threshold. Ratings with at least this
               threshold will automatically be accepted.
        :param interactive: Ratings with at least this threshold are presented
               to the user for interactive rating.  Ratings below this threshold
               will automatically be discarded.
        :param diff_lines_ratio: Minimum ratio of shorter diff / longer diff
        :param heading: Minimum similarity rating of the section heading of a
               diff
        :param filename: Minimum similarity of two filenames for being evaluated
               (files in a repo may move).
        :param message_diff_weight: heuristic factor of message rating to diff
               rating
        :param author_date_interval: Used for preevaluation: Two patches will only
               be considered for comparison, if the difference of their
               author_dates is within patch_time_window days. A value of 0
               means infinite days.
        """

        # t_a
        self.autoaccept = autoaccept
        # t_i
        self.interactive = interactive
        # t_h
        self.heading = heading
        # t_f
        self.filename = filename
        # w
        self.message_diff_weight = message_diff_weight
        # dlr
        self.diff_lines_ratio = diff_lines_ratio
        # ptw
        self.author_date_interval = author_date_interval


class PygitCredentials(pygit2.RemoteCallbacks):
    def credentials(self, url, username_from_url, allowed_types):
        if allowed_types & pygit2.credentials.GIT_CREDTYPE_SSH_KEY:
            return pygit2.KeypairFromAgent(username_from_url)
        else:
            return None


def merge_dicts(default_cfg, cfg):
    for key in default_cfg.keys():
        if key not in cfg:
            cfg[key] = default_cfg[key]
        elif type(default_cfg[key]) == dict:
            merge_dicts(default_cfg[key], cfg[key])
        elif key not in cfg:
            cfg[key] = default_cfg[key]


class Config:
    D_RESOURCES = 'resources'
    D_COMMON = join(D_RESOURCES, 'common')

    D_PROJECT_ROOT = join(D_RESOURCES, '%s')

    # Configuration file containing default parameters
    DEFAULT_CONFIG = join(D_COMMON, 'default.cfg')
    BLACKLIST_LOCATION = join(D_COMMON, 'blacklists')

    class Mode(Enum):
        MBOX = "mbox"
        PATCHSTACK = "patchstack"

    def __init__(self, project, debug):
        self.debug = debug
        self._project_root, self._config_file = Config.get_config_dir_file(project)

        if not isfile(Config.DEFAULT_CONFIG):
            raise FileNotFoundError('Default config file \'%s\' not found' %
                                    Config.DEFAULT_CONFIG)

        if not isfile(self._config_file):
            raise FileNotFoundError('Config file \'%s\' not found' %
                                    project)
        else:
            log.info('Active configuration: %s' % project)


        default_cfg = toml.load(Config.DEFAULT_CONFIG)
        cfg = toml.load(self._config_file)

        # Merge configs
        merge_dicts(default_cfg, cfg)

        pasta = cfg['PaStA']

        # Obligatory values
        self.project_name = pasta.get('PROJECT_NAME')
        if not self.project_name:
            raise RuntimeError('Project name not found')

        self._mode = Config.Mode(pasta['MODE'])

        self.repo_location = pasta.get('REPO')
        if not self.repo_location:
            raise RuntimeError('Location of repository not found')
        self.repo_location = join(self._project_root, self.repo_location)
        self.repo = Repository(self.repo_location)

        self.upstream_range = pasta.get('UPSTREAM')
        if not self.upstream_range:
            raise RuntimeError('Please provide a valid upstream range in your '
                               'config')

        def path(name):
            return join(self._project_root, pasta[name])

        # parse locations, those will fallback to default values
        self.f_patch_stack_definition = path('PATCH_STACK_DEFINITION')

        # commit hash files and mailbox ID files
        self.d_stack_hashes = path('STACK_HASHES')
        if not isdir(self.d_stack_hashes):
            makedirs(self.d_stack_hashes)

        self.f_upstream_hashes = join(self.d_stack_hashes, 'upstream')

        # commit hash blacklist
        self.upstream_blacklist = pasta.get('UPSTREAM_BLACKLIST')

        # analysis results
        self.d_false_positives = path('FALSE_POSTITIVES')

        self.f_pasta_result = path('PASTA_RESULT')
        self.f_mbox_result = path('MBOX_RESULT')

        self.f_commit_description = path('COMMIT_DESCRIPTION')

        self.f_upstream_duration = path('UPSTREAM_DURATION')

        # pkl commit cache (ccache) and result files
        self.f_evaluation_result = path('EVALUATION_RESULT')
        self.f_ccache_stack = path('COMMIT_CACHE_STACK')
        self.f_ccache_upstream = path('COMMIT_CACHE_UPSTREAM')
        self.f_ccache_mbox = path('COMMIT_CACHE_MBOX')

        # R location
        self.R_resources = path('R_RESOURCES')

        if self.upstream_blacklist:
            self.upstream_blacklist = join(Config.BLACKLIST_LOCATION,
                                           self.upstream_blacklist)

        # default thresholds
        self.thresholds = Thresholds(float(pasta.get('AUTOACCEPT_THRESHOLD')),
                                     float(pasta.get('INTERACTIVE_THRESHOLD')),
                                     float(pasta.get('DIFF_LINES_RATIO')),
                                     float(pasta.get('HEADING_THRESHOLD')),
                                     float(pasta.get('FILENAME_THRESHOLD')),
                                     float(pasta.get('MESSAGE_DIFF_WEIGHT')),
                                     int(pasta.get('AUTHOR_DATE_INTERVAL')))

        self.upstream_hashes = None
        self.load_upstream_hashes()

        if self._mode == Config.Mode.PATCHSTACK:
            self.patch_stack_definition = \
                PatchStackDefinition.parse_definition_file(self)
        elif self._mode == Config.Mode.MBOX:
            self.f_mail_thread_cache = path('MAIL_THREAD_CACHE')
            self.d_mbox = path('MBOX')

            mbox = cfg['mbox']
            mbox_raw = mbox['raw']
            mbox_pub_in = mbox['pubin']

            # mailbox parameters
            self.mbox_mindate = parse_date_ymd(mbox['MBOX_MINDATE'])
            self.mbox_maxdate = parse_date_ymd(mbox['MBOX_MAXDATE'])
            try:
                self.time_frame = parse_date_ymd(mbox['TIME_FRAME'])
            except KeyError as e:
                log.warning('Timeframe not defined in config')
                self.time_frame = None

            self.mbox_raw = list()
            for listname, f_mbox_raw in mbox_raw.items():
                if not isabs(f_mbox_raw):
                    f_mbox_raw = join(self.d_mbox, 'raw', f_mbox_raw)
                self.mbox_raw.append((listname, f_mbox_raw))

            self.mbox_git_public_inbox = list()
            for host, mailinglists in mbox_pub_in.items():
                mailinglists = mailinglists['lists']
                self.mbox_git_public_inbox.append((host, mailinglists))

    @property
    def project_root(self):
        return self._project_root

    def load_ccache_upstream(self):
        self.repo.load_ccache(self.f_ccache_upstream, 'upstream')

    def load_ccache_mbox(self):
        self.repo.load_ccache(self.f_ccache_mbox, 'mbox')

    def load_ccache_stack(self):
        self.repo.load_ccache(self.f_ccache_stack, 'stack')

    def _update_ccache(self, f_ccache, commits, desc):
        repo = self.repo
        repo.clear_commit_cache()
        repo.load_ccache(f_ccache, desc)
        cached = repo.cache_commits(commits)
        if cached:
            repo.export_ccache(f_ccache)
        repo.clear_commit_cache()

    def update_ccache_upstream(self):
        self._update_ccache(self.f_ccache_upstream, self.upstream_hashes,
                            'upstream')

    def update_ccache_mbox(self):
        self._update_ccache(self.f_ccache_mbox, self.repo.mbox.message_ids(),
                            'mbox')

    def update_ccache_stack(self):
        self._update_ccache(self.f_ccache_stack, self.psd.commits_on_stacks,
                            'stack')

    def load_patch_groups(self, must_exist=True, f_patch_groups=None):
        if f_patch_groups is None:
            f_patch_groups = self.f_pasta_result
            if self.mode == Config.Mode.MBOX:
                self.repo.register_mbox(self)
                f_patch_groups = self.f_mbox_result

        if must_exist:
            Config.fail_result_not_exists(f_patch_groups)

        patch_groups = Cluster.from_file(f_patch_groups, must_exist=must_exist)

        return f_patch_groups, patch_groups

    def load_upstream_hashes(self, force_reload=False):
        # check if upstream commit hashes are existent. If not, create them
        upstream = None
        if isfile(self.f_upstream_hashes):
            upstream = load_commit_hashes(self.f_upstream_hashes)

            # check if upstream range in the config file is in sync
            if not upstream or upstream.pop(0) != self.upstream_range or \
               force_reload:
                # set upstream to None if inconsistencies are detected.
                # upstream commit hash file will be renewed in the next step.
                upstream = None

        if not upstream:
            log.info('Renewing upstream commit hash file')
            upstream = self.repo.get_commithash_range(self.upstream_range)
            persist_commit_hashes(self.f_upstream_hashes,
                                  [self.upstream_range] + upstream)
            log.info('  ↪ done')

        if self.upstream_blacklist:
            log.debug('Loading upstream blacklist')
            blacklist = load_commit_hashes(self.upstream_blacklist,
                                           ordered=False)
            # filter blacklistes commit hashes
            log.debug('  Excluding %d commits from upstream commit list'
                      % len(blacklist))
            upstream = [x for x in upstream if x not in blacklist]
            log.debug('  ↪ done')

        self.upstream_hashes = upstream

    @staticmethod
    def get_config_dir_file(project):
        project_root = realpath(Config.D_PROJECT_ROOT % project)
        config_file = join(project_root, 'config')

        return project_root, config_file

    @staticmethod
    def select_config(project):
        _, config_file = Config.get_config_dir_file(project)

        if not isfile(config_file):
            log.error('Unable to select %s: configuration missing' % project)
            return -1

        with open('./config', 'w') as config_select:
            config_select.write('%s\n' % project)

        log.info('Successfully set active configuration: %s' % project)

    @staticmethod
    def fail_result_not_exists(filename):
        if not isfile(filename):
            log.error('Result %s not existent' % filename)
            log.error('Run \'pasta analyse ...\' first.')
            quit(-1)

    @property
    def psd(self):
        return self.patch_stack_definition

    @property
    def mode(self):
        return self._mode
